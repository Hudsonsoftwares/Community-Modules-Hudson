# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, date
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class DentalAppointment(models.Model):
    _name = 'dental.appointment'
    _description = 'Dental Appointment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

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
        tracking=True
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

    # ---------------------------------------------------------
    # Computes & Onchanges
    # ---------------------------------------------------------
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
                            fields.Datetime.to_string(leaves.date_from),
                            fields.Datetime.to_string(leaves.date_to)
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
                        elif eq.maintenance_open_count and eq.maintenance_open_count > 0:
                            # Check active corrective breakdown requests
                            active_reqs = self.env['maintenance.request'].sudo().search([
                                ('equipment_id', '=', eq.id),
                                ('stage_id.done', '=', False),
                                ('maintenance_type', '=', 'corrective')
                            ], limit=1)
                            if active_reqs:
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
                                      getattr(e, 'equipment_condition', 'operational') not in ('under_repair', 'out_of_order', 'scrapped')
                        )
                        # If NONE are operational in this branch, all are down!
                        if not oper_equips:
                            unavailable_equips |= all_cat_equips

            if unavailable_equips:
                app.has_equipment_conflict = True
                app.conflicting_equipment_ids = [(6, 0, unavailable_equips.ids)]
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
        return appointments

    def write(self, vals):
        res = super().write(vals)
        if set(vals.keys()) & {'date_start', 'date_end', 'state', 'patient_id', 'doctor_id', 'treatment_id', 'appointment_type_id', 'branch_id'}:
            self._sync_calendar_event()
            self._check_appointment_equipment_availability()
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
                    raise ValidationError(_("Doctor %s is on approved leave during this time (%s to %s). Please reschedule this appointment.") % (
                        record.doctor_id.name,
                        fields.Datetime.to_string(leaves[0].date_from),
                        fields.Datetime.to_string(leaves[0].date_to)
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
                raise ValidationError(_("Doctor %s already has an appointment during this time (%s to %s).") % (
                    record.doctor_id.name,
                    fields.Datetime.to_string(record.date_start),
                    fields.Datetime.to_string(record.date_end)
                ))

            # Check branch consistency if doctor is assigned to a specific company
            if record.branch_id and record.doctor_id.company_id and record.doctor_id.company_id != record.branch_id:
                raise ValidationError(_("Doctor %s belongs to branch '%s', but appointment is booked for branch '%s'.") % (
                    record.doctor_id.name, record.doctor_id.company_id.name, record.branch_id.name
                ))

    # ---------------------------------------------------------
    # State Action Methods
    # ---------------------------------------------------------
    def action_confirm(self):
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

    def action_check_in(self):
        for record in self:
            if record.state in ['checked_in', 'in_consultation', 'completed', 'cancelled']:
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

    def action_start_consultation(self):
        for record in self:
            record.write({
                'state': 'in_consultation',
                'called_time': fields.Datetime.now()
            })

    def action_complete(self):
        for record in self:
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
                
            treatment_name = (appt.treatment_id.name or appt.reason or '').lower()
            if any(w in treatment_name for w in ['surgery', 'extraction', 'implant', 'wisdom']):
                days_delta = 3
                reason_txt = f"Post-Surgical Suture & Healing Check: {appt.treatment_id.name or 'Surgery / Extraction'}"
            elif any(w in treatment_name for w in ['root canal', 'endodontic', 'rct']):
                days_delta = 7
                reason_txt = f"RCT Follow-up & Permanent Restoration: {appt.treatment_id.name or 'Root Canal'}"
            elif any(w in treatment_name for w in ['braces', 'ortho', 'aligner']):
                days_delta = 28
                reason_txt = f"Orthodontic Adjustment Checkup: {appt.treatment_id.name or 'Braces'}"
            elif any(w in treatment_name for w in ['filling', 'crown', 'bridge', 'restoration']):
                days_delta = 7
                reason_txt = f"Post-Restoration Occlusion & Sensitivity Check: {appt.treatment_id.name or 'Filling / Crown'}"
            elif any(w in treatment_name for w in ['scaling', 'cleaning', 'prophylaxis']):
                days_delta = 14
                reason_txt = f"Gingival Health & Post-Scaling Review: {appt.treatment_id.name or 'Scaling'}"
            else:
                days_delta = 7
                reason_txt = f"Post-Treatment Review: {appt.treatment_id.name or appt.reason or 'Consultation'}"
                
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
        for record in self:
            record.state = 'cancelled'
            if record.calendar_event_id:
                record.calendar_event_id.sudo().unlink()

    def action_no_show(self):
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
    # Shared Business Logic: Patient Lookup & Matching
    # ---------------------------------------------------------
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
    def get_available_slots(self, date=None, doctor_id=None, duration=30, branch_id=None, **kwargs):
        """Return available time slots for a given date, doctor, duration, and branch."""
        target_date_str = date or fields.Date.context_today(self).strftime('%Y-%m-%d')
        if hasattr(target_date_str, 'strftime'):
            target_date_str = target_date_str.strftime('%Y-%m-%d')
        try:
            target_date_obj = datetime.strptime(str(target_date_str), '%Y-%m-%d').date()
        except Exception:
            target_date_obj = date.today()
            target_date_str = target_date_obj.strftime('%Y-%m-%d')

        duration_val = float(duration or 30.0)
        now = datetime.now()
        is_today = (target_date_obj == now.date())

        weekday = target_date_obj.weekday()
        if weekday == 6:  # Sunday
            raw_slots = [
                ('10:00', '10:00 AM', 'morning'),
                ('10:30', '10:30 AM', 'morning'),
                ('11:00', '11:00 AM', 'morning'),
                ('11:30', '11:30 AM', 'morning'),
                ('12:00', '12:00 PM', 'morning'),
                ('12:30', '12:30 PM', 'morning'),
                ('13:00', '01:00 PM', 'afternoon'),
                ('13:30', '01:30 PM', 'afternoon'),
            ]
        else:
            raw_slots = [
                ('09:00', '09:00 AM', 'morning'),
                ('09:30', '09:30 AM', 'morning'),
                ('10:00', '10:00 AM', 'morning'),
                ('10:30', '10:30 AM', 'morning'),
                ('11:00', '11:00 AM', 'morning'),
                ('11:30', '11:30 AM', 'morning'),
                ('12:00', '12:00 PM', 'morning'),
                ('12:30', '12:30 PM', 'morning'),
                ('14:00', '02:00 PM', 'afternoon'),
                ('14:30', '02:30 PM', 'afternoon'),
                ('15:00', '03:00 PM', 'afternoon'),
                ('15:30', '03:30 PM', 'afternoon'),
                ('16:00', '04:00 PM', 'afternoon'),
                ('16:30', '04:30 PM', 'afternoon'),
                ('17:00', '05:00 PM', 'afternoon'),
                ('17:30', '05:30 PM', 'afternoon'),
            ]

        # Resolve Branch
        branch = None
        if branch_id:
            try:
                branch = self.env['res.company'].sudo().browse(int(branch_id))
                if not branch.exists():
                    branch = None
            except Exception:
                branch = None

        emp_obj = self.env['hr.employee'].sudo()
        doc_domain = [('is_dentist', '=', True), ('active', '=', True)]
        if branch:
            doc_domain = [('is_dentist', '=', True), ('active', '=', True), '|', ('company_id', '=', False), ('company_id', '=', branch.id)]

        all_dentists = emp_obj.search(doc_domain, order='id asc')
        if not all_dentists:
            all_dentists = emp_obj.search([('is_dentist', '=', True), ('active', '=', True)], order='id asc')
        if not all_dentists:
            all_dentists = emp_obj.search([('id', 'in', [1, 4])], order='id asc')

        selected_doc = None
        if doctor_id and str(doctor_id).strip() not in ('', '0', 'any', 'None'):
            try:
                if str(doctor_id).isdigit():
                    selected_doc = emp_obj.browse(int(doctor_id))
                else:
                    selected_doc = emp_obj.search([('name', 'ilike', str(doctor_id).strip()), ('is_dentist', '=', True)], limit=1)
                if not selected_doc.exists():
                    selected_doc = None
            except Exception:
                selected_doc = None

        candidate_docs = [selected_doc] if selected_doc else all_dentists
        leave_obj = self.env['hr.leave'].sudo()

        slots_result = []
        for slot_time, label, period in raw_slots:
            slot_dt_start = datetime.strptime(f"{target_date_str} {slot_time}:00", '%Y-%m-%d %H:%M:%S')
            slot_dt_end = slot_dt_start + timedelta(minutes=duration_val)

            if is_today and slot_dt_start <= (now + timedelta(minutes=15)):
                slots_result.append({
                    'time': slot_time,
                    'label': label,
                    'period': period,
                    'available': False,
                    'reason': 'Past Time'
                })
                continue

            free_docs = []
            for doc in candidate_docs:
                overlap = self.sudo().search_count([
                    ('doctor_id', '=', doc.id),
                    ('state', 'not in', ['cancelled', 'no_show']),
                    ('date_start', '<', slot_dt_end),
                    ('date_end', '>', slot_dt_start),
                ])
                if overlap > 0:
                    continue

                leaves = leave_obj.search_count([
                    ('employee_id', '=', doc.id),
                    ('state', '=', 'validate'),
                    ('date_from', '<', slot_dt_end),
                    ('date_to', '>', slot_dt_start),
                ])
                if leaves > 0:
                    continue

                free_docs.append(doc.id)

            is_avail = len(free_docs) > 0
            slots_result.append({
                'time': slot_time,
                'label': label,
                'period': period,
                'available': is_avail,
                'reason': '' if is_avail else ('Doctor Booked' if selected_doc else 'Fully Booked'),
                'available_doctors': free_docs
            })

        return {
            'success': True,
            'date': target_date_str,
            'weekday': target_date_obj.strftime('%A'),
            'slots': slots_result,
        }

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
                date_start = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
            elif len(clean_time.split(':')) == 3 and not any(x in clean_time.lower() for x in ['am', 'pm']):
                dt_str = f"{appointment_date} {clean_time}"
                date_start = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
            else:
                dt_str = f"{appointment_date} {clean_time.replace('.', '').upper()}"
                date_start = datetime.strptime(dt_str, '%Y-%m-%d %I:%M %p')
            date_end = date_start + timedelta(minutes=duration)
        except Exception as e:
            _logger.error("Failed to parse appointment datetime: %s", e)
            return {'success': False, 'error': _('Invalid date or time format.')}

        is_internal = self.env.user and self.env.user.has_group('base.group_user')
        allow_past = post.get('allow_past', False) or self.env.context.get('allow_past', False) or is_internal
        try:
            booking_date_obj = datetime.strptime(str(appointment_date), '%Y-%m-%d').date()
            today_date = fields.Date.context_today(self)
            if not allow_past and booking_date_obj < today_date:
                return {'success': False, 'error': _('Cannot book an appointment for past dates. Please select an upcoming date.')}
        except Exception:
            pass

        # Resolve Branch / Company
        branch = None
        if branch_id:
            try:
                branch = self.env['res.company'].sudo().browse(int(branch_id))
                if not branch.exists():
                    branch = self.env.company
            except Exception:
                branch = self.env.company
        else:
            branch = self.env.company

        # Resolve Doctor & Validate Availability
        emp_obj = self.env['hr.employee'].sudo()
        doctor = None
        if doctor_id and str(doctor_id).strip() not in ('', '0', 'any', 'None'):
            try:
                if str(doctor_id).isdigit():
                    doctor = emp_obj.browse(int(doctor_id))
                else:
                    doctor = emp_obj.search([('name', 'ilike', str(doctor_id).strip()), ('is_dentist', '=', True)], limit=1)
                if not doctor.exists():
                    doctor = None
            except Exception:
                doctor = None

        leave_obj = self.env['hr.leave'].sudo()

        if doctor:
            # Transaction row lock on doctor to prevent race conditions during concurrent bookings
            try:
                self.env.cr.execute("SELECT id FROM hr_employee WHERE id = %s FOR UPDATE NOWAIT", (doctor.id,))
            except Exception:
                pass

            overlap = self.sudo().search_count([
                ('doctor_id', '=', doctor.id),
                ('state', 'not in', ['cancelled', 'no_show']),
                ('date_start', '<', date_end),
                ('date_end', '>', date_start),
            ])
            if overlap > 0:
                return {
                    'success': False,
                    'error': _('Doctor %s is already booked for this time slot (%s - %s). Please pick another time or choose Any Specialist.') % (
                        doctor.name, appointment_time, date_end.strftime('%H:%M')
                    )
                }

            leaves = leave_obj.search_count([
                ('employee_id', '=', doctor.id),
                ('state', '=', 'validate'),
                ('date_from', '<', date_end),
                ('date_to', '>', date_start),
            ])
            if leaves > 0:
                return {
                    'success': False,
                    'error': _('Doctor %s is on scheduled leave during this time. Please pick another time.') % doctor.name
                }
        else:
            doc_domain = [('is_dentist', '=', True), ('active', '=', True)]
            if branch:
                doc_domain = [('is_dentist', '=', True), ('active', '=', True), '|', ('company_id', '=', False), ('company_id', '=', branch.id)]
            all_dentists = emp_obj.search(doc_domain, order='id asc')
            if not all_dentists:
                all_dentists = emp_obj.search([('is_dentist', '=', True), ('active', '=', True)], order='id asc')
            if not all_dentists:
                all_dentists = emp_obj.search([('id', 'in', [1, 4])], order='id asc')

            for d in all_dentists:
                overlap = self.sudo().search_count([
                    ('doctor_id', '=', d.id),
                    ('state', 'not in', ['cancelled', 'no_show']),
                    ('date_start', '<', date_end),
                    ('date_end', '>', date_start),
                ])
                if overlap == 0:
                    leaves = leave_obj.search_count([
                        ('employee_id', '=', d.id),
                        ('state', '=', 'validate'),
                        ('date_from', '<', date_end),
                        ('date_to', '>', date_start),
                    ])
                    if leaves == 0:
                        doctor = d
                        break

            if not doctor:
                return {
                    'success': False,
                    'error': _('All dental specialists are fully booked for this time slot. Please choose another date or time.')
                }

        # Resolve Patient
        try:
            patient = self.match_or_create_patient(post)
        except ValidationError as ve:
            return {'success': False, 'error': str(ve)}
        except Exception as e:
            return {'success': False, 'error': _('Error processing patient information: %s') % str(e)}

        # Resolve Treatment
        treatment = None
        if treatment_id:
            try:
                treatment = self.env['product.template'].sudo().browse(int(treatment_id))
                if not treatment.exists():
                    treatment = None
            except Exception:
                treatment = None
        if not treatment:
            treatment = self.env['product.template'].sudo().search([('is_dental_treatment', '=', True)], limit=1)

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
                'date_formatted': date_start.strftime('%A, %B %d, %Y'),
                'time_str': appointment_time,
                'time_formatted': date_start.strftime('%I:%M %p'),
                'status': 'Confirmed' if booking_state == 'confirmed' else 'Pending Confirmation',
            }
        except Exception as e:
            _logger.exception("Error booking dental appointment: %s", e)
            return {'success': False, 'error': str(e)}
