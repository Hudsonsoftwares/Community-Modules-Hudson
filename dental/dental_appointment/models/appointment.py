# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, date
import logging
import pytz
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

# Clinic opening hours in local time: (period key, label, hour from, hour to).
# A service is only offered at a start time when it also ends inside the same session.
CLINIC_SESSIONS = {
    'weekday': [('morning', 'Morning', 9.0, 13.0), ('afternoon', 'Afternoon', 14.0, 18.0)],
    'sunday': [('morning', 'Sunday Hours', 10.0, 14.0)],
}


class DentalAppointment(models.Model):
    _name = 'dental.appointment'
    _description = 'Dental Appointment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Appointment Number',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New')
    )
    patient_id = fields.Many2one(
        'res.partner',
        string='Patient',
        required=True,
        domain=[('is_dental_patient', '=', True)],
        tracking=True
    )
    doctor_id = fields.Many2one(
        'hr.employee.public',
        string='Doctor',
        required=True,
        domain=[('is_dentist', '=', True)],
        tracking=True
    )
    treatment_id = fields.Many2one(
        'product.template',
        string='Dental Treatment',
        domain=[('is_dental_treatment', '=', True)],
        tracking=True,
        check_company=True,
    )
    appointment_type_id = fields.Many2one(
        'dental.appointment.type',
        string='Appointment Type',
        tracking=True
    )

    date_start = fields.Datetime(string='Start Time', required=True, tracking=True)
    date_end = fields.Datetime(string='End Time', required=True, tracking=True)
    duration = fields.Float(string='Duration (Hours)', compute='_compute_duration', store=True)

    reason = fields.Text(string='Reason / Chief Complaint')
    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Very High')
    ], string='Priority', default='1')
    notes = fields.Html(string='Notes')

    branch_id = fields.Many2one(
        'res.company',
        string='Branch / Clinic',
        required=True,
        default=lambda self: self.env.company
    )
    # Standard company field (mirrors branch_id) used by record rules and check_company validation
    company_id = fields.Many2one(related='branch_id', store=True, index=True, string='Company')

    state = fields.Selection([
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('checked_in', 'Checked In'),
        ('in_consultation', 'In Consultation'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show')
    ], string='Status', default='pending', tracking=True, copy=False)

    calendar_event_id = fields.Many2one('calendar.event', string='Calendar Event', copy=False, ondelete='set null')

    is_emergency = fields.Boolean(string='Emergency', default=False, tracking=True)
    token_number = fields.Char(string='Token Number', readonly=True, copy=False)
    queue_priority = fields.Integer(string='Queue Priority', compute='_compute_queue_priority', store=True)

    check_in_time = fields.Datetime(string='Check-in Time', readonly=True, copy=False)
    called_time = fields.Datetime(string='Called Time', readonly=True, copy=False)
    waiting_time = fields.Float(string='Waiting Time (Minutes)', compute='_compute_waiting_time')

    has_leave_conflict = fields.Boolean(
        string='Doctor Leave Conflict',
        default=False,
        tracking=True,
        copy=False,
        help='Technical flag indicating the doctor is on approved leave during this appointment slot'
    )
    conflicting_leave_id = fields.Many2one(
        'hr.leave',
        string='Conflicting Leave',
        ondelete='set null',
        copy=False,
        tracking=True
    )

    has_equipment_conflict = fields.Boolean(
        string='Equipment Conflict Alert',
        default=False,
        tracking=True,
        copy=False,
        help='Indicates required dental equipment is currently under maintenance or unavailable in this clinic branch'
    )
    conflicting_equipment_ids = fields.Many2many(
        'maintenance.equipment',
        'dental_appt_conflict_equip_rel',
        'appointment_id',
        'equipment_id',
        string='Unavailable Equipment',
        copy=False
    )
    equipment_conflict_reason = fields.Char(
        string='Equipment Availability Notice',
        tracking=True,
        copy=False
    )

    # Clinic hours alert (informational: booking outside hours stays allowed)
    outside_clinic_hours = fields.Boolean(
        string='Outside Clinic Hours', compute='_compute_outside_clinic_hours',
        help='The appointment is not within the clinic hours set in Clinic Configuration.')

    is_receptionist = fields.Boolean(
        string='Is Receptionist',
        compute='_compute_is_receptionist',
        help='True if current user is front-desk receptionist or clinic administrator.'
    )

    def _compute_is_receptionist(self):
        can_check = self._can_check_in()
        for record in self:
            record.is_receptionist = can_check
    clinic_hours_warning = fields.Char(string='Clinic Hours Notice', compute='_compute_outside_clinic_hours')

    # ---------------------------------------------------------
    # Computes & Onchanges
    # ---------------------------------------------------------
    @api.depends('date_start', 'date_end', 'branch_id')
    def _compute_outside_clinic_hours(self):
        for record in self:
            record.clinic_hours_warning = record._get_clinic_hours_warning()
            record.outside_clinic_hours = bool(record.clinic_hours_warning)

    def _log_outside_clinic_hours(self):
        """Leave a visible note on appointments scheduled outside clinic hours (never blocks)."""
        for record in self:
            if record.state in ('cancelled', 'no_show', 'completed'):
                continue
            warning = record._get_clinic_hours_warning()
            if warning:
                record.message_post(body=_("Clinic hours alert: %s", warning))

    def _get_clinic_hours_warning(self):
        self.ensure_one()
        if not self.date_start or not self.date_end:
            return False
        clinic = (self.branch_id or self.env.company).sudo()
        tz = self._get_clinic_tz(clinic)
        start_local = pytz.utc.localize(self.date_start).astimezone(tz).replace(tzinfo=None)
        end_local = pytz.utc.localize(self.date_end).astimezone(tz).replace(tzinfo=None)
        return clinic._dental_outside_hours_message(start_local, end_local)

    @api.onchange('date_start', 'date_end', 'branch_id')
    def _onchange_clinic_hours_alert(self):
        warning = self._get_clinic_hours_warning()
        if warning:
            return {'warning': {'title': _("Outside Clinic Hours"), 'message': warning, 'type': 'notification'}}

    @api.depends('date_start', 'date_end')
    def _compute_duration(self):
        for record in self:
            if record.date_start and record.date_end:
                diff = record.date_end - record.date_start
                record.duration = diff.total_seconds() / 3600.0
            else:
                record.duration = 0.0

    @api.onchange('date_start', 'appointment_type_id')
    def _onchange_date_start(self):
        if self.date_start:
            dur_mins = 30
            if self.appointment_type_id and self.appointment_type_id.duration:
                dur_mins = self.appointment_type_id.duration
            self.date_end = self.date_start + timedelta(minutes=float(dur_mins))

    @api.depends('is_emergency')
    def _compute_queue_priority(self):
        for record in self:
            record.queue_priority = 10 if record.is_emergency else 5

    @api.depends('check_in_time', 'called_time', 'state')
    def _compute_waiting_time(self):
        for record in self:
            if record.check_in_time:
                end_time = record.called_time or fields.Datetime.now()
                diff = end_time - record.check_in_time
                record.waiting_time = max(0.0, diff.total_seconds() / 60.0)
            else:
                record.waiting_time = 0.0

    @api.onchange('doctor_id', 'date_start', 'date_end')
    def _onchange_doctor_leave_availability(self):
        if self.doctor_id and self.date_start and self.date_end:
            leaves = self.env['hr.leave'].sudo().search([
                ('employee_id', '=', self.doctor_id.id),
                ('state', '=', 'validate'),
                ('date_from', '<', self.date_end),
                ('date_to', '>', self.date_start)
            ], limit=1)
            if leaves:
                self.has_leave_conflict = True
                self.conflicting_leave_id = leaves.id
                return {
                    'warning': {
                        'title': _("Doctor Availability Conflict"),
                        'message': _("Doctor %s is on approved leave from %s to %s. Please pick another time slot or another doctor.") % (
                            self.doctor_id.name,
                            self._format_local(leaves.date_from, self._get_clinic_tz(self.branch_id)),
                            self._format_local(leaves.date_to, self._get_clinic_tz(self.branch_id))
                        )
                    }
                }
            else:
                self.has_leave_conflict = False
                self.conflicting_leave_id = False

    @api.onchange('appointment_type_id', 'branch_id')
    def _onchange_equipment_availability(self):
        """Check if any equipment required by this appointment type is marked unavailable."""
        warning_msg = self._check_appointment_equipment_availability()
        if warning_msg:
            return {
                'warning': {
                    'title': _("Equipment Availability Notice"),
                    'message': warning_msg
                }
            }

    def _check_appointment_equipment_availability(self):
        """Evaluate required equipment availability without blocking or auto-cancelling."""
        for app in self:
            appt_type = app.appointment_type_id
            if not appt_type:
                app.has_equipment_conflict = False
                app.conflicting_equipment_ids = [(5, 0, 0)]
                app.equipment_conflict_reason = False
                continue

            # Only check if appointment type requires equipment
            req_equipments = appt_type.required_equipment_ids
            req_categories = appt_type.required_equipment_category_ids
            if not req_equipments and not req_categories:
                app.has_equipment_conflict = False
                app.conflicting_equipment_ids = [(5, 0, 0)]
                app.equipment_conflict_reason = False
                continue

            branch_id = app.branch_id.id if app.branch_id else self.env.company.id
            unavailable_equips = self.env['maintenance.equipment']

            # 1. Check specific required equipment items
            if req_equipments:
                for eq in req_equipments:
                    # If equipment belongs to this branch (or global) and is marked unavailable or under repair
                    if (not eq.company_id or eq.company_id.id == branch_id):
                        is_down = False
                        if hasattr(eq, 'is_available') and not eq.is_available:
                            is_down = True
                        elif hasattr(eq, 'equipment_condition') and eq.equipment_condition in ('under_repair', 'out_of_order', 'scrapped'):
                            is_down = True
                        elif getattr(eq, 'scrap_date', False):
                            is_down = True
                        else:
                            # Check active requests or scrap requests
                            req_match = self.env['maintenance.request'].sudo().search([
                                ('equipment_id', '=', eq.id),
                                '|',
                                ('stage_id.name', 'ilike', 'scrap'),
                                '&', ('stage_id.fold', '=', False), ('equipment_availability_impact', 'in', ('unavailable', 'reduced_capacity'))
                            ], limit=1)
                            if req_match:
                                is_down = True
                        if is_down:
                            unavailable_equips |= eq

            # 2. Check required equipment categories (e.g., Dental X-ray category)
            if req_categories:
                for cat in req_categories:
                    all_cat_equips = self.env['maintenance.equipment'].sudo().search([
                        ('category_id', '=', cat.id),
                        ('company_id', 'in', [False, branch_id])
                    ])
                    if all_cat_equips:
                        # Find operational ones
                        oper_equips = all_cat_equips.filtered(
                            lambda e: getattr(e, 'is_available', True) and
                                      not getattr(e, 'scrap_date', False) and
                                      getattr(e, 'equipment_condition', 'operational') not in ('under_repair', 'out_of_order', 'scrapped') and
                                      not e.maintenance_ids.filtered(lambda r: r.stage_id and ('scrap' in (r.stage_id.name or '').lower() or (not r.stage_id.fold and r.equipment_availability_impact == 'unavailable')))
                        )
                        # If NONE are operational in this branch, all are down!
                        if not oper_equips:
                            unavailable_equips |= all_cat_equips

            if unavailable_equips:
                app.has_equipment_conflict = True
                app.conflicting_equipment_ids = [(6, 0, unavailable_equips.ids)]
                scrapped_names = unavailable_equips.filtered(
                    lambda e: e.equipment_condition == 'scrapped' or getattr(e, 'scrap_date', False) or e.maintenance_ids.filtered(lambda r: r.stage_id and 'scrap' in (r.stage_id.name or '').lower())
                ).mapped('name')
                if scrapped_names:
                    app.equipment_conflict_reason = _(
                        "CRITICAL: Equipment '%s' has been SCRAPPED / Decommissioned in %s. Please reassign the appointment to an alternate operatory."
                    ) % (", ".join(scrapped_names), app.branch_id.name or 'this clinic')
                else:
                    eq_names = ", ".join(unavailable_equips.mapped('name'))
                    app.equipment_conflict_reason = _(
                        "Required equipment '%s' is currently under maintenance or unavailable in %s."
                    ) % (eq_names, app.branch_id.name or 'this clinic')
                return app.equipment_conflict_reason
            else:
                app.has_equipment_conflict = False
                app.conflicting_equipment_ids = [(5, 0, 0)]
                app.equipment_conflict_reason = False
                return False

    # ---------------------------------------------------------
    # ORM Overrides
    # ---------------------------------------------------------
    @api.model
    def default_get(self, fields_list):
        if self.env.context:
            ctx = dict(self.env.context)
            modified = False
            for key in ('default_date_start', 'default_date_end'):
                val = ctx.get(key)
                if isinstance(val, str) and 'T' in val:
                    clean_val = val.replace('T', ' ').split('.')[0].replace('Z', '').strip()
                    ctx[key] = clean_val
                    modified = True
            if modified:
                self = self.with_context(ctx)
        return super().default_get(fields_list)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('dental.appointment') or _('New')
            if 'branch_id' not in vals or not vals['branch_id']:
                vals['branch_id'] = self.env.company.id
        appointments = super().create(vals_list)
        appointments._sync_calendar_event()
        appointments._check_appointment_equipment_availability()
        appointments._log_outside_clinic_hours()
        appointments._link_follow_up_from_context()
        return appointments

    def _link_follow_up_from_context(self):
        """Book the follow-up that opened this appointment form (see action_book_followup_appointment)."""
        follow_up_id = self.env.context.get('dental_follow_up_id')
        if not follow_up_id or len(self) != 1:
            return
        follow_up = self.env['dental.follow.up'].browse(follow_up_id).exists()
        if follow_up:
            follow_up._link_booked_appointment(self)

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals:
            self.env['dental.follow.up'].sudo().search(
                [('booked_appointment_id', 'in', self.ids), ('state', '=', 'booked')])._sync_from_booked_appointment()
        if set(vals.keys()) & {'date_start', 'date_end', 'state', 'patient_id', 'doctor_id', 'treatment_id', 'appointment_type_id', 'branch_id'}:
            self._sync_calendar_event()
            self._check_appointment_equipment_availability()
        if {'date_start', 'date_end', 'branch_id'} & set(vals):
            self._log_outside_clinic_hours()
        return res

    def unlink(self):
        events = self.mapped('calendar_event_id')
        res = super().unlink()
        events.sudo().unlink()
        return res

    # ---------------------------------------------------------
    # Calendar Synchronization
    # ---------------------------------------------------------
    def _sync_calendar_event(self):
        res_model_id = self.env['ir.model'].sudo()._get_id('dental.appointment')
        for app in self:
            if app.state in ['cancelled', 'no_show'] and app.calendar_event_id:
                app.calendar_event_id.sudo().unlink()
            elif app.state not in ['cancelled', 'no_show'] and app.date_start and app.date_end:
                title = f"Dental: {app.patient_id.name}"
                if app.treatment_id:
                    title += f" - {app.treatment_id.name}"
                elif app.appointment_type_id:
                    title += f" - {app.appointment_type_id.name}"

                vals = {
                    'name': title,
                    'start': app.date_start,
                    'stop': app.date_end,
                    'description': app.reason,
                    'res_model_id': res_model_id,
                    'res_id': app.id,
                }
                partners = [app.patient_id.id]
                if app.doctor_id.user_id and app.doctor_id.user_id.partner_id:
                    partners.append(app.doctor_id.user_id.partner_id.id)
                vals['partner_ids'] = [(6, 0, partners)]

                if app.calendar_event_id:
                    app.calendar_event_id.sudo().write(vals)
                else:
                    event = self.env['calendar.event'].sudo().create(vals)
                    app.calendar_event_id = event.id

    # ---------------------------------------------------------
    # Doctor Availability Constraints
    # ---------------------------------------------------------
    @api.constrains('doctor_id', 'date_start', 'date_end', 'state', 'branch_id')
    def _check_doctor_availability(self):
        for record in self:
            if record.state in ['cancelled', 'no_show']:
                continue
            if not record.doctor_id or not record.date_start or not record.date_end:
                continue

            # Check approved leave in hr.leave
            leaves = self.env['hr.leave'].sudo().search([
                ('employee_id', '=', record.doctor_id.id),
                ('state', '=', 'validate'),
                ('date_from', '<', record.date_end),
                ('date_to', '>', record.date_start)
            ])
            if leaves:
                if record.state == 'pending':
                    record.has_leave_conflict = True
                    record.conflicting_leave_id = leaves[0].id
                    continue
                else:
                    tz = self._get_clinic_tz(record.branch_id)
                    raise ValidationError(_("Doctor %s is on approved leave during this time (%s to %s). Please reschedule this appointment.") % (
                        record.doctor_id.name,
                        self._format_local(leaves[0].date_from, tz),
                        self._format_local(leaves[0].date_to, tz)
                    ))
            elif record.has_leave_conflict:
                record.has_leave_conflict = False
                record.conflicting_leave_id = False

            # Check overlap with existing appointments
            domain = [
                ('id', '!=', record.id),
                ('doctor_id', '=', record.doctor_id.id),
                ('state', 'not in', ['cancelled', 'no_show', 'pending']),
                ('date_start', '<', record.date_end),
                ('date_end', '>', record.date_start)
            ]
            if record.state != 'pending' and self.search_count(domain) > 0:
                tz = self._get_clinic_tz(record.branch_id)
                raise ValidationError(_("Doctor %s already has an appointment during this time (%s to %s).") % (
                    record.doctor_id.name,
                    self._format_local(record.date_start, tz),
                    self._format_local(record.date_end, tz, '%I:%M %p')
                ))

            # Check the doctor's maximum appointments per day
            if record.state != 'pending':
                tz = self._get_clinic_tz(record.branch_id)
                local_day = pytz.utc.localize(record.date_start).astimezone(tz).date()
                if self._doctor_day_limit_reached(record.doctor_id, local_day, tz, exclude_id=record.id):
                    raise ValidationError(_("Doctor %s has reached the maximum of %s appointments on %s.") % (
                        record.doctor_id.name,
                        record.doctor_id.sudo().max_appointments_per_day,
                        local_day.strftime('%d %b %Y'),
                    ))

            # Check branch consistency if doctor is assigned to a specific company
            if record.branch_id and record.doctor_id.company_id and record.doctor_id.company_id != record.branch_id:
                raise ValidationError(_("Doctor %s belongs to branch '%s', but appointment is booked for branch '%s'.") % (
                    record.doctor_id.name, record.doctor_id.company_id.name, record.branch_id.name
                ))

    # ---------------------------------------------------------
    # State Action Methods
    # ---------------------------------------------------------
    def _check_state_transition(self, allowed_states, action_label):
        """Raise a clear error when a workflow button is used from an invalid status."""
        state_labels = dict(self._fields['state'].selection)
        for record in self:
            if record.state not in allowed_states:
                raise UserError(_("Cannot %(action)s appointment %(name)s while it is '%(state)s'.") % {
                    'action': action_label,
                    'name': record.name,
                    'state': state_labels.get(record.state, record.state),
                })

    def action_confirm(self):
        self.filtered(lambda r: r.state != 'confirmed')._check_state_transition(['pending'], _('confirm'))
        for record in self:
            if record.state == 'confirmed':
                continue
            record.state = 'confirmed'

            # Ensure patient record is properly stamped as dental patient
            if record.patient_id:
                p_vals = {}
                if not record.patient_id.is_dental_patient:
                    p_vals['is_dental_patient'] = True
                    p_vals['customer_rank'] = 1
                if not record.patient_id.dental_patient_id or record.patient_id.dental_patient_id == 'New':
                    p_vals['dental_patient_id'] = self.env['ir.sequence'].next_by_code('dental.patient') or ('PT-%05d' % record.patient_id.id)
                if p_vals:
                    record.patient_id.sudo().write(p_vals)

            # Send confirmation email
            if not record.patient_id.email:
                record.message_post(body=_('Warning: Could not send confirmation email. Patient has no email address configured.'))
            else:
                template = self.env.ref('dental_appointment.email_template_appointment_confirmation', raise_if_not_found=False)
                if template:
                    template.send_mail(record.id, force_send=False)
                    record.message_post(body=_('Appointment confirmation email sent/queued to %s.') % record.patient_id.email)

    @api.model
    def _can_check_in(self):
        """Checking in a patient is a front-desk reception act: allowed for Receptionists and Dental Administrators.
        Doctors start the visit from the Dentist Workspace once the patient is checked in."""
        if self.env.su:
            return True
        user = self.env.user
        # Dental Administrator and System Administrator always have access
        if (
            user.has_group('dental_base.group_dental_admin')
            or user.has_group('base.group_system')
        ):
            return True

        # Front-desk receptionists have access
        if (
            user.has_group('dental_base.group_dental_receptionist')
            or bool(user.employee_id and user.employee_id.dental_role == 'receptionist')
        ):
            return True

        # Doctors (without receptionist or administrator permissions) cannot check in
        return False

    def action_check_in(self):
        if not self._can_check_in():
            raise AccessError(_("Only receptionists can check in patients. Doctors start the visit from the Dentist Workspace once the patient is checked in."))
        for record in self:
            if record.state in ['checked_in', 'in_consultation', 'completed', 'cancelled', 'no_show']:
                continue

            if not record.token_number:
                branch_code = 'APT'
                if hasattr(record.branch_id, 'name') and record.branch_id.name:
                    branch_code = ''.join(e for e in record.branch_id.name if e.isalnum())[:3].upper()
                    if not branch_code:
                        branch_code = 'APT'

                date_str = fields.Date.context_today(record).strftime('%Y%m%d')
                seq = self.env['ir.sequence'].next_by_code('dental.queue.token') or '001'
                record.token_number = f"{branch_code}-{date_str}-{seq}"

            record.write({
                'state': 'checked_in',
                'check_in_time': fields.Datetime.now()
            })
            # The live queue follows the check-in time; keep an audit trail when it differs from the booking
            booked_day = fields.Datetime.context_timestamp(record, record.date_start).date() if record.date_start else False
            if booked_day and booked_day != fields.Date.context_today(record):
                record.message_post(body=_(
                    "Patient checked in on %(today)s for an appointment booked on %(booked)s. "
                    "The visit is in today's queue for Dr. %(doctor)s.",
                    today=fields.Date.context_today(record), booked=booked_day, doctor=record.doctor_id.name))

    @api.model
    def _can_start_consultation(self):
        """Starting a consultation is a clinical act: only users with the Dentist permission
        (including receptionists who are also dentists). A receptionist alone cannot."""
        return self.env.su or self.env.user.has_group('dental_base.group_dental_dentist')

    def action_start_consultation(self):
        if not self._can_start_consultation():
            raise AccessError(_("Only dentists can start a consultation. The front desk checks the patient in; "
                                "the doctor starts the visit from the Dentist Workspace."))
        to_start = self.filtered(lambda r: r.state != 'in_consultation')
        to_start._check_state_transition(['confirmed', 'checked_in'], _('start the consultation for'))
        # Walk-ins seen directly from 'confirmed' are checked in first so queue/waiting data stays consistent
        to_start.filtered(lambda r: r.state == 'confirmed').sudo().action_check_in()
        for record in to_start:
            record.write({
                'state': 'in_consultation',
                'called_time': fields.Datetime.now()
            })

    def action_complete(self):
        to_complete = self.filtered(lambda r: r.state != 'completed')
        to_complete._check_state_transition(['checked_in', 'in_consultation'], _('complete'))
        for record in to_complete:
            record.state = 'completed'
            record._create_automatic_followup()

    def _create_automatic_followup(self):
        """Automatically schedule a follow-up and recall when an appointment is completed."""
        follow_up_obj = self.env['dental.follow.up'].sudo()
        recall_obj = self.env['dental.recall'].sudo()
        today = fields.Date.today()
        
        for appt in self:
            if not appt.patient_id:
                continue
                
            days_delta, reason_txt = follow_up_obj._suggest_followup(appt.treatment_id, appt.reason)

            follow_up_date = today + timedelta(days=days_delta)
            
            existing = follow_up_obj.search([
                ('patient_id', '=', appt.patient_id.id),
                ('appointment_id', '=', appt.id),
                ('state', '=', 'pending')
            ], limit=1)
            
            if not existing:
                follow_up_obj.create({
                    'patient_id': appt.patient_id.id,
                    'appointment_id': appt.id,
                    'doctor_id': appt.doctor_id.id if appt.doctor_id else False,
                    'treatment_id': appt.treatment_id.id if appt.treatment_id else False,
                    'date': follow_up_date,
                    'reason': reason_txt,
                    'state': 'pending',
                    'notes': f"Auto-scheduled follow-up for Dr. {appt.doctor_id.name or 'Specialist'} after appointment on {today}."
                })
                
            # Routine 6-month recall
            six_months_date = today + timedelta(days=180)
            existing_recall = recall_obj.search([
                ('patient_id', '=', appt.patient_id.id),
                ('state', '=', 'pending'),
                ('due_date', '>=', today)
            ], limit=1)
            if not existing_recall:
                recall_obj.create({
                    'patient_id': appt.patient_id.id,
                    'last_appointment_id': appt.id,
                    'treatment_id': appt.treatment_id.id if appt.treatment_id else False,
                    'due_date': six_months_date,
                    'state': 'pending',
                    'notes': f"Routine 6-month preventive recall following visit on {today}."
                })

    def action_cancel(self):
        self._check_state_transition(['pending', 'confirmed', 'checked_in', 'cancelled'], _('cancel'))
        for record in self:
            record.state = 'cancelled'
            if record.calendar_event_id:
                record.calendar_event_id.sudo().unlink()

    def action_no_show(self):
        self._check_state_transition(['pending', 'confirmed', 'checked_in'], _('mark as no-show'))
        for record in self:
            record.state = 'no_show'
            if record.calendar_event_id:
                record.calendar_event_id.sudo().unlink()

    def action_reschedule(self):
        for record in self:
            record.state = 'pending'
            record.has_leave_conflict = False
            record.conflicting_leave_id = False
            record.message_post(body=_("Appointment marked for rescheduling. Please select an available slot."))
        return True

    def action_open_booking_flow(self):
        """Open the modern guided 5-step booking flow client action."""
        return {
            'type': 'ir.actions.client',
            'tag': 'dental_appointment.book_appointment_flow',
            'target': 'current',
        }

    # ---------------------------------------------------------
    # Shared Business Logic: Bookable Services
    # ---------------------------------------------------------
    @api.model
    def _resolve_booking_branch(self, branch_id=None):
        if branch_id:
            try:
                branch = self.env['res.company'].sudo().browse(int(branch_id))
                if branch.exists():
                    # Booking runs with sudo: never let an internal user book into a branch they cannot access
                    return self.env['dental.company.mixin']._dental_check_company_access(branch.with_env(self.env))
            except (ValueError, TypeError):
                pass
        return self.env.company

    @api.model
    def _get_bookable_treatment_domain(self, branch=None):
        """Catalog services that can be booked: active, sellable dental services shared or owned by the branch."""
        domain = [
            ('is_dental_treatment', '=', True),
            ('active', '=', True),
            ('sale_ok', '=', True),
            ('type', '=', 'service'),
        ]
        if branch:
            domain += ['|', ('company_id', '=', False), ('company_id', '=', branch.id)]
        return domain

    @api.model
    def get_bookable_services(self, branch_id=None):
        """Return every service the given branch can book: appointment types plus catalog treatments.

        A treatment and an appointment type sharing the same name are merged into a single entry so the
        receptionist never sees duplicates, while the booking still records both.
        """
        branch = self._resolve_booking_branch(branch_id)
        appt_types = self.env['dental.appointment.type'].sudo().search([('active', '=', True)], order='id asc')
        treatments = self.env['product.template'].sudo().search(
            self._get_bookable_treatment_domain(branch), order='sequence asc, name asc')

        services = []
        by_name = {}
        for atype in appt_types:
            item = {
                'key': f'type_{atype.id}',
                'appointment_type_id': atype.id,
                'treatment_id': False,
                'name': atype.name,
                'duration': atype.duration or 30,
                'description': atype.description or '',
                'price': atype.price or 0.0,
                'category': _('Consultation & Visits'),
                'icon': atype.icon or 'fa-stethoscope',
                'icon_type': atype.icon_type or 'icon',
                'has_custom_image': bool(atype.image),
                'image_url': f'/web/image/dental.appointment.type/{atype.id}/image' if atype.image else False,
            }
            services.append(item)
            by_name[(atype.name or '').strip().lower()] = item

        for treatment in treatments:
            duration = round((treatment.treatment_duration or 0.0) * 60) or 30
            existing = by_name.get((treatment.name or '').strip().lower())
            if existing:
                existing['treatment_id'] = treatment.id
                existing['price'] = existing['price'] or treatment.list_price
                existing['category'] = treatment.dental_treatment_category_id.name or existing['category']
                continue
            services.append({
                'key': f'treatment_{treatment.id}',
                'appointment_type_id': False,
                'treatment_id': treatment.id,
                'name': treatment.name,
                'duration': duration,
                'description': treatment.description_sale or '',
                'price': treatment.list_price,
                'category': treatment.dental_treatment_category_id.name or _('Dental Treatments'),
            })
        return {
            'branch_id': branch.id,
            'branch_name': branch.name,
            'services': services,
        }

    # ---------------------------------------------------------
    # Shared Business Logic: Patient Lookup & Matching
    # ---------------------------------------------------------
    @api.model
    def search_booking_patients(self, term='', limit=8):
        """Live patient finder for the staff booking flow: name, phone, email or Patient ID.

        Staff only, and run with the user's own access rights (branch rules apply). The public
        website keeps using check_patient, which only matches exact identifiers.
        """
        if not self.env.user._is_internal():
            raise AccessError(_("Only clinic staff can search patient records."))
        term = (term or '').strip()
        if len(term) < 2:
            return []
        limit = max(1, min(int(limit or 8), 20))
        criteria = [('name', 'ilike', term), ('phone', 'ilike', term),
                    ('email', 'ilike', term), ('dental_patient_id', 'ilike', term)]
        digits = ''.join(c for c in term if c.isdigit())
        if len(digits) >= 4 and digits != term:
            criteria.append(('phone', 'ilike', digits))
        domain = [('is_dental_patient', '=', True)] + ['|'] * (len(criteria) - 1) + criteria
        patients = self.env['res.partner'].search(domain, limit=limit, order='name, id')
        return [self._booking_patient_payload(p) for p in patients]

    @api.model
    def get_booking_patient(self, patient_id):
        """One patient for the booking flow (e.g. just registered), with the user's access rights."""
        if not self.env.user._is_internal():
            raise AccessError(_("Only clinic staff can search patient records."))
        patient = self.env['res.partner'].browse(int(patient_id)).exists()
        patient.check_access('read')
        return self._booking_patient_payload(patient) if patient else False

    @api.model
    def _booking_patient_payload(self, patient):
        return {
            'id': patient.id,
            'name': patient.name or '',
            'phone': patient.phone or '',
            'email': patient.email or '',
            'dental_patient_id': patient.dental_patient_id or '',
            'gender': patient.gender or '',
            'date_of_birth': str(patient.date_of_birth) if patient.date_of_birth else '',
            'age': patient.age or 0,
        }

    @api.model
    def check_patient(self, identifier=None):
        """Search for an existing patient by phone number, email, or patient ID."""
        if not identifier:
            return {'found': False, 'message': _('Please enter a mobile phone number, email, or Patient ID.')}

        clean_id = str(identifier).strip()
        partner_obj = self.env['res.partner'].sudo()

        domain = [
            ('is_dental_patient', '=', True),
            '|', '|',
            ('phone', '=', clean_id),
            ('email', '=ilike', clean_id),
            ('dental_patient_id', '=ilike', clean_id),
        ]
        patient = partner_obj.search(domain, limit=1)

        clean_digits = ''.join([c for c in clean_id if c.isdigit()])
        if not patient and clean_digits and len(clean_digits) >= 7:
            patient = partner_obj.search([
                ('is_dental_patient', '=', True),
                ('phone', 'ilike', clean_digits),
            ], limit=1)

        if patient:
            pat_data = {
                'id': patient.id,
                'name': patient.name,
                'phone': patient.phone or '',
                'email': patient.email or '',
                'dental_patient_id': patient.dental_patient_id or ('PT-%05d' % patient.id),
                'gender': patient.gender or '',
                'date_of_birth': str(patient.date_of_birth) if patient.date_of_birth else '',
            }
            return {
                'found': True,
                'id': patient.id,
                'name': patient.name,
                'phone': patient.phone or '',
                'email': patient.email or '',
                'dental_patient_id': patient.dental_patient_id or ('PT-%05d' % patient.id),
                'patient': pat_data,
            }
        else:
            return {
                'found': False,
                'message': _('No patient record found matching "%s". You can easily register as a New Patient.') % clean_id
            }

    @api.model
    def match_or_create_patient(self, post):
        """Find an existing patient or create a new patient record safely without duplicate records."""
        partner_obj = self.env['res.partner'].sudo()
        patient_type = post.get('patient_type', 'new')
        branch_id = post.get('branch_id')

        if patient_type in ('returning', 'existing'):
            existing_id = post.get('patient_id')
            if not existing_id:
                raise ValidationError(_('Patient record not specified.'))
            patient = partner_obj.browse(int(existing_id))
            if not patient.exists():
                raise ValidationError(_('Selected patient record does not exist.'))
            if not patient.is_dental_patient or not patient.dental_patient_id or patient.dental_patient_id == 'New':
                seq = self.env['ir.sequence'].next_by_code('dental.patient') or ('PT-%05d' % patient.id)
                patient.sudo().write({
                    'is_dental_patient': True,
                    'dental_patient_id': seq if (not patient.dental_patient_id or patient.dental_patient_id == 'New') else patient.dental_patient_id
                })
            return patient

        # New patient workflow: search for existing record by phone, cleaned digits, or email
        name = (post.get('name') or '').strip()
        phone = (post.get('phone') or '').strip()
        email = (post.get('email') or '').strip()
        dob = post.get('dob') or False
        gender = post.get('gender') or False

        if not name:
            raise ValidationError(_('Please enter your full name.'))
        if not phone:
            raise ValidationError(_('Please enter your phone number.'))

        clean_digits = ''.join([c for c in phone if c.isdigit()])
        existing = partner_obj.search([
            '|',
            ('phone', '=', phone),
            ('phone', '=ilike', phone),
        ], limit=1)
        if not existing and clean_digits and len(clean_digits) >= 7:
            existing = partner_obj.search([
                ('phone', 'ilike', clean_digits),
            ], limit=1)
        if not existing and email:
            existing = partner_obj.search([
                ('email', '=ilike', email),
            ], limit=1)

        if existing:
            patient = existing
            updates = {
                'is_dental_patient': True,
                'customer_rank': 1,
            }
            if name and not patient.name:
                updates['name'] = name
            if email and not patient.email:
                updates['email'] = email
            if dob and not patient.date_of_birth:
                updates['date_of_birth'] = dob
            if gender and not patient.gender:
                updates['gender'] = gender
            if not patient.dental_patient_id or patient.dental_patient_id == 'New':
                seq = self.env['ir.sequence'].next_by_code('dental.patient') or ('PT-%05d' % patient.id)
                updates['dental_patient_id'] = seq
            patient.sudo().write(updates)
            return patient

        # Create new patient
        create_vals = {
            'name': name,
            'phone': phone,
            'email': email or False,
            'date_of_birth': dob or False,
            'gender': gender or False,
            'is_dental_patient': True,
            'customer_rank': 1,
        }
        if branch_id:
            try:
                b_id = int(branch_id)
                if self.env['res.company'].browse(b_id).exists():
                    create_vals['active_clinic_id'] = b_id
            except (ValueError, TypeError):
                pass
        patient = partner_obj.create(create_vals)
        if not patient.dental_patient_id or patient.dental_patient_id == 'New':
            seq = self.env['ir.sequence'].next_by_code('dental.patient') or ('PT-%05d' % patient.id)
            patient.sudo().write({'dental_patient_id': seq})
        return patient

    # ---------------------------------------------------------
    # Shared Business Logic: Availability & Slots
    # ---------------------------------------------------------
    @api.model
    def _get_clinic_tz(self, branch=None):
        """Clinic hours are local times: use the branch timezone, else the user's, else the admin's."""
        tz_name = branch.partner_id.tz if branch else False
        if not tz_name and not self.env.user._is_public():
            tz_name = self.env.user.tz
        if not tz_name:
            admin = self.env.ref('base.user_admin', raise_if_not_found=False)
            tz_name = admin.sudo().tz if admin else False
        try:
            return pytz.timezone(tz_name or 'UTC')
        except pytz.UnknownTimeZoneError:
            return pytz.utc

    @api.model
    def _to_utc(self, local_dt, tz):
        """Naive clinic-local datetime -> naive UTC datetime as stored by Odoo."""
        return tz.localize(local_dt).astimezone(pytz.utc).replace(tzinfo=None)

    @api.model
    def _format_local(self, utc_dt, tz, fmt='%d %b %Y %I:%M %p'):
        return pytz.utc.localize(utc_dt).astimezone(tz).strftime(fmt)

    @api.model
    def _get_slot_step(self, branch=None):
        """Clinic's own slot length (Clinic Configuration), else the global default."""
        return max((branch or self.env.company).sudo()._dental_get_slot_duration(), 5)

    @api.model
    def _get_clinic_sessions(self, target_date, branch=None):
        """Working sessions of the clinic on that day (Clinic Configuration > Clinic Hours);
        built-in standard timings when the clinic has none configured."""
        clinic = branch or self.env.company
        sessions = clinic.sudo()._dental_get_sessions(target_date.weekday())
        if sessions is not None:
            return sessions
        return CLINIC_SESSIONS['sunday' if target_date.weekday() == 6 else 'weekday']

    @api.model
    def _resolve_booking_doctors(self, branch=None, doctor_id=None):
        """(selected doctor or None, all candidate dentists of the branch)."""
        emp_obj = self.env['hr.employee'].sudo()
        domain = [('is_dentist', '=', True), ('active', '=', True)]
        if branch:
            domain += ['|', ('company_id', '=', False), ('company_id', '=', branch.id)]
        dentists = emp_obj.search(domain, order='id asc') or emp_obj.search(
            [('is_dentist', '=', True), ('active', '=', True)], order='id asc')
        selected = None
        if doctor_id and str(doctor_id).strip() not in ('', '0', 'any', 'None', 'null', 'false'):
            if str(doctor_id).isdigit():
                selected = emp_obj.browse(int(doctor_id)).exists() or None
            else:
                selected = emp_obj.search([('name', 'ilike', str(doctor_id).strip()), ('is_dentist', '=', True)], limit=1) or None
        return selected, dentists

    @api.model
    def _doctor_day_limit_reached(self, doctor, local_date, tz, exclude_id=None):
        """True when the doctor already has their 'Max Appointments / Day' on this clinic-local date (0 = no limit)."""
        limit = doctor.sudo().max_appointments_per_day
        if not limit:
            return False
        day_start = datetime.combine(local_date, datetime.min.time())
        domain = [
            ('doctor_id', '=', doctor.id),
            ('state', 'not in', ['cancelled', 'no_show']),
            ('date_start', '>=', self._to_utc(day_start, tz)),
            ('date_start', '<', self._to_utc(day_start + timedelta(days=1), tz)),
        ]
        if exclude_id:
            domain.append(('id', '!=', exclude_id))
        return self.sudo().search_count(domain) >= limit

    @api.model
    def _is_doctor_free(self, doctor, start_utc, end_utc):
        overlap = self.sudo().search_count([
            ('doctor_id', '=', doctor.id),
            ('state', 'not in', ['cancelled', 'no_show']),
            ('date_start', '<', end_utc),
            ('date_end', '>', start_utc),
        ])
        if overlap:
            return False
        return not self.env['hr.leave'].sudo().search_count([
            ('employee_id', '=', doctor.id),
            ('state', '=', 'validate'),
            ('date_from', '<', end_utc),
            ('date_to', '>', start_utc),
        ])

    @api.model
    def _compute_day_slots(self, target_date, doctors, duration, tz, branch=None):
        """Slots of one clinic day. A slot is offered only if the whole service fits inside the session."""
        now_local = datetime.now(pytz.utc).astimezone(tz).replace(tzinfo=None)
        step = timedelta(minutes=self._get_slot_step(branch))
        length = timedelta(minutes=duration)
        day_start = datetime.combine(target_date, datetime.min.time())
        # Doctors who already reached their daily appointment limit are not offered on this day
        capped = {d.id for d in doctors if self._doctor_day_limit_reached(d, target_date, tz)}
        open_doctors = [d for d in doctors if d.id not in capped]
        slots = []
        for period, _label, hour_from, hour_to in self._get_clinic_sessions(target_date, branch):
            start = day_start + timedelta(hours=hour_from)
            session_end = day_start + timedelta(hours=hour_to)
            while start + length <= session_end:
                slot = {
                    'time': start.strftime('%H:%M'),
                    'label': start.strftime('%I:%M %p'),
                    'end_label': (start + length).strftime('%I:%M %p'),
                    'period': period,
                    'available': False,
                    'reason': '',
                    'available_doctors': [],
                }
                if start <= now_local + timedelta(minutes=15):
                    slot['reason'] = _('Past time')
                else:
                    start_utc, end_utc = self._to_utc(start, tz), self._to_utc(start + length, tz)
                    slot['available_doctors'] = [d.id for d in open_doctors if self._is_doctor_free(d, start_utc, end_utc)]
                    slot['available'] = bool(slot['available_doctors'])
                    if not slot['available']:
                        if doctors and not open_doctors:
                            slot['reason'] = _('Daily limit reached')
                        else:
                            slot['reason'] = _('Booked') if len(doctors) == 1 else _('Fully booked')
                slots.append(slot)
                start += step
        return slots

    @api.model
    def get_available_slots(self, date=None, doctor_id=None, duration=30, branch_id=None, **kwargs):
        """Available time slots for a date, doctor, duration and branch, in the clinic's local time.

        Slot times are clinic-local "HH:MM"; availability is checked against stored UTC appointments and leaves.
        """
        branch = self._resolve_booking_branch(branch_id) if branch_id else None
        tz = self._get_clinic_tz(branch)
        today_local = datetime.now(pytz.utc).astimezone(tz).date()
        try:
            target_date = datetime.strptime(str(date)[:10], '%Y-%m-%d').date() if date else today_local
        except ValueError:
            target_date = today_local
        try:
            duration_val = max(int(float(duration or 30)), 5)
        except (TypeError, ValueError):
            duration_val = 30

        selected_doc, dentists = self._resolve_booking_doctors(branch, doctor_id)
        doctors = [selected_doc] if selected_doc else list(dentists)
        periods = [{
            'key': period,
            'label': label,
            'range': '%s - %s' % (
                (datetime.min + timedelta(hours=h_from)).strftime('%I:%M %p'),
                (datetime.min + timedelta(hours=h_to)).strftime('%I:%M %p')),
        } for period, label, h_from, h_to in self._get_clinic_sessions(target_date, branch)]

        result = {
            'success': True,
            'date': target_date.strftime('%Y-%m-%d'),
            'weekday': target_date.strftime('%A'),
            'date_label': target_date.strftime('%a, %d %b %Y'),
            'today': today_local.strftime('%Y-%m-%d'),
            'timezone': tz.zone,
            'periods': periods,
            'slots': [],
            'message': '',
            'next_available_date': False,
            'next_available_label': '',
        }
        if target_date < today_local:
            result['message'] = _('This date has already passed. Please choose today or a future date.')
        else:
            result["slots"] = self._compute_day_slots(target_date, doctors, duration_val, tz, branch)
        if not any(s['available'] for s in result['slots']):
            # Help the user: find the next day with a free slot (two weeks ahead)
            probe = max(target_date, today_local)
            for _i in range(14):
                probe += timedelta(days=1)
                if any(s["available"] for s in self._compute_day_slots(probe, doctors, duration_val, tz, branch)):
                    result['next_available_date'] = probe.strftime('%Y-%m-%d')
                    result['next_available_label'] = probe.strftime('%a, %d %b %Y')
                    break
            if not result['message']:
                result['message'] = _('No free slots on this date for the selected doctor and service.')
        return result

    # ---------------------------------------------------------
    # Shared Business Logic: Appointment Booking
    # ---------------------------------------------------------
    @api.model
    def create_appointment_booking(self, post=None, **kwargs):
        """Unified transaction-safe appointment creation logic for website and backend channels."""
        if not post and kwargs:
            post = kwargs.get('post') or kwargs
        post = dict(post or {})
        appointment_date = post.get('appointment_date') or post.get('date_str')
        appointment_time = post.get('appointment_time') or post.get('time_str')
        notes = (post.get('notes') or post.get('reason') or '').strip()
        doctor_id = post.get('doctor_id')
        appointment_type_id = post.get('appointment_type_id')
        treatment_id = post.get('treatment_id')
        branch_id = post.get('branch_id')

        if not appointment_date or not appointment_time:
            return {'success': False, 'error': _('Please select an appointment date and time.')}

        # Resolve Appointment Type & Duration
        appt_type = None
        duration = float(post.get('duration') or post.get('duration_minutes') or 30.0)
        if appointment_type_id:
            try:
                appt_type = self.env['dental.appointment.type'].sudo().browse(int(appointment_type_id))
                if appt_type.exists() and appt_type.duration:
                    duration = float(appt_type.duration or 30.0)
            except Exception:
                appt_type = None

        try:
            clean_time = str(appointment_time).strip()
            if len(clean_time.split(':')) == 2 and not any(x in clean_time.lower() for x in ['am', 'pm']):
                dt_str = f"{appointment_date} {clean_time}:00"
                local_start = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
            elif len(clean_time.split(':')) == 3 and not any(x in clean_time.lower() for x in ['am', 'pm']):
                dt_str = f"{appointment_date} {clean_time}"
                local_start = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
            else:
                dt_str = f"{appointment_date} {clean_time.replace('.', '').upper()}"
                local_start = datetime.strptime(dt_str, '%Y-%m-%d %I:%M %p')
        except Exception as e:
            _logger.error("Failed to parse appointment datetime: %s", e)
            return {'success': False, 'error': _('Invalid date or time format.')}

        is_internal = self.env.user and self.env.user.has_group('base.group_user')
        # Explicit opt-in only (e.g. data imports); normal bookings must use a real, free clinic slot
        allow_past = post.get('allow_past', False) or self.env.context.get('allow_past', False)

        branch = self._resolve_booking_branch(branch_id)
        tz = self._get_clinic_tz(branch)

        # Picked times are clinic-local; Odoo stores UTC
        local_end = local_start + timedelta(minutes=duration)
        date_start = self._to_utc(local_start, tz)
        date_end = self._to_utc(local_end, tz)
        when_label = '%s, %s - %s' % (local_start.strftime('%a %d %b %Y'), local_start.strftime('%I:%M %p'), local_end.strftime('%I:%M %p'))

        # Resolve Treatment (only when one was explicitly chosen and is bookable at this branch)
        treatment = None
        if treatment_id:
            try:
                treatment = self.env['product.template'].sudo().search(
                    [('id', '=', int(treatment_id))] + self._get_bookable_treatment_domain(branch), limit=1)
            except (ValueError, TypeError):
                treatment = None
            if not treatment:
                return {'success': False, 'error': _('The selected service is not available for booking at this branch.')}

        # Resolve Doctor & validate the slot with the same rules as the slot picker
        selected_doc, dentists = self._resolve_booking_doctors(branch, doctor_id)
        if doctor_id and str(doctor_id).strip() not in ('', '0', 'any', 'None', 'null', 'false') and not selected_doc:
            return {'success': False, 'error': _('The selected doctor is not available for booking.')}
        if allow_past:
            candidates = [selected_doc] if selected_doc else list(dentists)
        else:
            day_slots = self._compute_day_slots(local_start.date(), [selected_doc] if selected_doc else list(dentists), duration, tz, branch)
            slot = next((s for s in day_slots if s['time'] == local_start.strftime('%H:%M')), None)
            if not slot:
                return {'success': False, 'error': _(
                    '%(when)s is outside clinic hours for a %(minutes)s-minute service. Please choose one of the offered time slots.',
                    when=when_label, minutes=int(duration))}
            if not slot['available']:
                return {'success': False, 'error': _('%(when)s is no longer available (%(reason)s). Please pick another time.',
                                                     when=when_label, reason=slot['reason'] or _('booked'))}
            candidates = [selected_doc] if selected_doc else self.env['hr.employee'].sudo().browse(slot['available_doctors'])

        # Lock each candidate doctor and re-check, so two receptionists cannot book the same slot at once
        doctor = None
        for candidate in candidates:
            self.env.cr.execute("SELECT id FROM hr_employee WHERE id = %s FOR UPDATE", (candidate.id,))
            if self._is_doctor_free(candidate, date_start, date_end) and \
                    not self._doctor_day_limit_reached(candidate, local_start.date(), tz):
                doctor = candidate
                break
        if not doctor:
            if selected_doc:
                return {'success': False, 'error': _(
                    'Dr. %(doctor)s is not available at %(when)s. Please pick another time or choose Any Specialist.',
                    doctor=selected_doc.name, when=when_label)}
            return {'success': False, 'error': _(
                'All dental specialists are booked at %(when)s. Please choose another date or time.', when=when_label)}

        # Resolve Patient
        try:
            patient = self.match_or_create_patient(post)
        except ValidationError as ve:
            return {'success': False, 'error': str(ve)}
        except Exception as e:
            return {'success': False, 'error': _('Error processing patient information: %s') % str(e)}

        service_title = appt_type.name if appt_type else (treatment.name if treatment else 'Dental Appointment')
        reason_text = service_title
        if notes:
            reason_text = f"{service_title} - {notes}"

        # Create Appointment Record
        try:
            booking_state = post.get('state') or ('confirmed' if is_internal else 'pending')
            appt_vals = {
                'patient_id': patient.id,
                'doctor_id': doctor.id,
                'appointment_type_id': appt_type.id if appt_type else False,
                'treatment_id': treatment.id if treatment else False,
                'branch_id': branch.id if branch else False,
                'date_start': date_start,
                'date_end': date_end,
                'reason': reason_text,
                'notes': notes,
                'state': booking_state,
                'priority': str(post.get('priority', '1')),
            }
            appointment = self.sudo().create(appt_vals)

            try:
                template = self.env.ref('dental_appointment.email_template_appointment_confirmation', raise_if_not_found=False)
                if template and patient.email:
                    template.sudo().send_mail(appointment.id, force_send=False)
            except Exception as mail_err:
                _logger.info("Email confirmation skipped: %s", mail_err)

            return {
                'success': True,
                'appointment_id': appointment.id,
                'appointment_name': appointment.name,
                'appointment_ref': appointment.name,
                'patient_name': patient.name,
                'patient_id': patient.dental_patient_id or ('PT-%05d' % patient.id),
                'doctor_name': doctor.name,
                'doctor_specialization': getattr(doctor, 'specialization', False) or 'Dental Specialist',
                'service_name': service_title,
                'duration_min': int(duration),
                'date_str': appointment_date,
                'date_formatted': local_start.strftime('%A, %B %d, %Y'),
                'time_str': appointment_time,
                'time_formatted': local_start.strftime('%I:%M %p'),
                'end_time_formatted': local_end.strftime('%I:%M %p'),
                'status': 'Confirmed' if booking_state == 'confirmed' else 'Pending Confirmation',
            }
        except Exception as e:
            _logger.exception("Error booking dental appointment: %s", e)
            return {'success': False, 'error': str(e)}
