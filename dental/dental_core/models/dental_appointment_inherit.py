from datetime import datetime, date, time, timedelta
import calendar
import pytz
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import format_amount

from .account_move import dental_billing_summary
from .res_users import DENTIST_WORKSPACE_GROUPS

class DentalAppointment(models.Model):
    _inherit = 'dental.appointment'

    case_ids = fields.One2many('dental.case', 'appointment_id', string='Clinical Cases')
    case_count = fields.Integer(string='Case Count', compute='_compute_case_count')
    # The dental case this visit belongs to: the case it opened, or an earlier case it continues
    case_id = fields.Many2one(
        'dental.case', string='Dental Case', compute='_compute_case_id', store=True, readonly=False,
        index=True, copy=False, tracking=True, check_company=True,
        help='Follow-up visits continue the patient\'s existing case instead of opening a new one.')

    is_case_continuation = fields.Boolean(string='Follow-up Visit', compute='_compute_is_case_continuation')
    # Shown on the visit cards of a case's Overview tab
    case_chief_complaint = fields.Text(related='case_id.chief_complaint', string='Case Complaint')

    @api.depends('case_ids')
    def _compute_case_id(self):
        for appt in self:
            appt.case_id = appt.case_ids[:1] or appt.case_id

    @api.depends('case_id')
    def _compute_is_case_continuation(self):
        for appt in self:
            case = appt.sudo().case_id
            appt.is_case_continuation = bool(case) and case.appointment_id.id != appt.id
    lead_id = fields.Many2one(
        'crm.lead',
        string='Originating CRM Enquiry',
        copy=False,
        tracking=True,
        help="The CRM enquiry or lead from which this appointment was booked."
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for appt in records:
            if appt.lead_id:
                lead = appt.lead_id
                lead.write({
                    'appointment_id': appt.id,
                    'conversion_status': 'appointment_scheduled',
                })
                # If lead stage is at sequence 1 (New), advance to next stage (Qualified)
                if lead.stage_id and not lead.stage_id.is_won:
                    next_stage = self.env['crm.stage'].search([
                        ('sequence', '>', lead.stage_id.sequence),
                        ('is_won', '=', False)
                    ], order='sequence asc', limit=1)
                    if next_stage:
                        lead.stage_id = next_stage.id
                lead.message_post(body=_(
                    "Dental appointment <b>%s</b> scheduled for %s on %s."
                ) % (appt.name, appt.patient_id.name or 'Patient', appt.date_start))
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals:
            for appt in self:
                if appt.lead_id:
                    if vals['state'] == 'completed':
                        appt.lead_id.write({'conversion_status': 'appointment_completed'})
                        appt.lead_id.message_post(body=_(
                            "Appointment <b>%s</b> was completed."
                        ) % appt.name)
                    elif vals['state'] == 'cancelled':
                        appt.lead_id.message_post(body=_(
                            "Appointment <b>%s</b> was cancelled. Status retained for receptionist follow-up."
                        ) % appt.name)
        return res

    @api.depends('case_id')
    def _compute_case_count(self):
        for appt in self:
            appt.case_count = 1 if appt.case_id else 0

    # ---------------------------------------------------------
    # Front-desk billing (receptionists have no access to clinical cases,
    # so the visit's case is read with sudo; invoices are still created as the user)
    # ---------------------------------------------------------
    billing_state = fields.Selection([
        ('nothing', 'Nothing to Bill'),
        ('to_invoice', 'To Invoice'),
        ('draft', 'Invoice in Draft'),
        ('due', 'Payment Due'),
        ('paid', 'Paid'),
    ], string='Billing Status', compute='_compute_billing', search='_search_billing_state')
    invoice_count = fields.Integer(string='Invoice Count', compute='_compute_billing')
    amount_due = fields.Monetary(string='Amount Due', compute='_compute_billing', currency_field='billing_currency_id')
    has_draft_invoice = fields.Boolean(compute='_compute_billing')
    billing_currency_id = fields.Many2one(related='branch_id.currency_id', string='Billing Currency')

    def _get_visit_invoices(self):
        self.ensure_one()
        case = self.sudo().case_id
        if case:
            return case.invoice_ids
        return self.env['account.move.line'].sudo().search([('dental_appointment_id', '=', self.id)]).move_id

    def _search_billing_state(self, operator, value):
        """Search on the computed billing status by narrowing to visits that can carry billing activity."""
        if operator not in ('=', 'in'):
            raise UserError(_("Unsupported search on Billing Status."))
        values = [value] if operator == '=' else list(value)
        if 'nothing' in values:
            raise UserError(_("Searching for visits with nothing to bill is not supported."))
        line_obj = self.env['account.move.line'].sudo()
        billed_lines = line_obj.search([('move_id.state', '!=', 'cancel'), '|',
                                        ('dental_appointment_id', '!=', False), ('dental_session_id', '!=', False)])
        appointments = self.sudo().browse()
        if 'to_invoice' in values:
            # Completed visits whose fee is unbilled, and visits with completed but unbilled treatment
            appointments |= self.sudo().search([('state', '=', 'completed'),
                                                 ('id', 'not in', billed_lines.dental_appointment_id.ids)])
            sessions = self.env['dental.treatment.session'].sudo().search([
                ('state', '=', 'completed'), ('id', 'not in', billed_lines.dental_session_id.ids)])
            appointments |= sessions.appointment_id | sessions.case_id.appointment_id
        if set(values) - {'to_invoice'}:
            # Visits that already have invoices
            appointments |= billed_lines.dental_appointment_id | billed_lines.dental_session_id.case_id.appointment_id
        return [('id', 'in', appointments.filtered(lambda a: a.billing_state in values).ids)]

    def _compute_billing(self):
        for appt in self:
            case = appt.sudo().case_id
            if case:
                has_billable = bool(case._get_billable_line_vals())
            else:
                has_billable = appt.state == 'completed' and bool(appt.sudo()._get_consultation_fee_line_vals())
            (appt.billing_state, appt.invoice_count, appt.amount_due,
             appt.has_draft_invoice) = dental_billing_summary(appt._get_visit_invoices(), has_billable)

    def _get_consultation_product(self):
        self.ensure_one()
        product = self.branch_id.dental_consultation_product_id or self.env.company.dental_consultation_product_id
        if not product:
            template = self.env.ref('dental_catalog.treatment_consultation', raise_if_not_found=False)
            product = template.product_variant_id if template else product
        return product

    def _get_consultation_fee_line_vals(self, doctor=None):
        """Consultation fee, billed once per appointment: doctor fee, else appointment type price, else service price."""
        self.ensure_one()
        if self.state in ('cancelled', 'no_show'):
            return False
        already_billed = self.env['account.move.line'].sudo().search_count([
            ('dental_appointment_id', '=', self.id),
            ('move_id.state', '!=', 'cancel'),
        ])
        product = self._get_consultation_product()
        if already_billed or not product:
            return False
        doctor = doctor or self.doctor_id
        # Read the fee from hr.employee itself; hr.employee.public is a SQL view over it
        doctor_fee = self.env['hr.employee'].sudo().browse(doctor.id).consultation_fee if doctor else 0.0
        price = doctor_fee or self.appointment_type_id.price or product.lst_price
        if not price:
            return False
        label = _('Consultation – Dr. %s', doctor.name) if doctor else _('Consultation')
        return {
            'product_id': product.id,
            'name': f"{label} ({self.name})",
            'quantity': 1.0,
            'price_unit': price,
            'dental_appointment_id': self.id,
        }

    def _create_visit_invoice(self):
        """Bill the visit: through its clinical case when there is one, otherwise the consultation fee only."""
        self.ensure_one()
        case = self.sudo().case_id
        if case:
            return case._create_patient_invoice()
        # Serialize concurrent billing of the same visit so it can never be invoiced twice
        self.env.cr.execute("SELECT id FROM dental_appointment WHERE id = %s FOR UPDATE", (self.id,))
        fee = self.sudo()._get_consultation_fee_line_vals()
        if not fee:
            return self.env['account.move']
        invoice, _extended = self.env['account.move']._dental_create_or_extend_invoice(
            self.patient_id, self.branch_id or self.env.company, [fee], origin=self.name)
        self.message_post(body=_("Consultation invoice prepared, total %s.", invoice.amount_total))
        return invoice

    def _check_billing_rights(self):
        """Front desk (Invoicing rights) and doctors may prepare invoices.

        Doctors only prepare drafts for records they can access; confirming invoices and
        collecting payments stay with standard Odoo Invoicing rights.
        """
        user = self.env.user
        if not (user.has_group('account.group_account_invoice') or user.has_group('dental_base.group_dental_dentist')):
            raise AccessError(_("You are not allowed to prepare patient invoices."))

    def _billing_result_action(self, invoice):
        """Open the invoice for billing staff; doctors without accounting access get a confirmation instead."""
        if self.env.user.has_group('account.group_account_invoice'):
            return self._action_open_visit_invoices(invoice.with_env(self.env))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _("Invoice of %(amount)s sent to Reception Desk > Billing > Ready for Billing.",
                             amount=invoice.amount_total),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_create_invoice(self):
        self.ensure_one()
        self._check_billing_rights()
        self.check_access('read')
        invoice = self.sudo()._create_visit_invoice()
        if not invoice:
            raise UserError(_("Nothing to invoice for this visit."))
        return self._billing_result_action(invoice)

    def action_view_invoices(self):
        self.ensure_one()
        return self._action_open_visit_invoices(
            self._get_visit_invoices().filtered(lambda m: m.move_type == 'out_invoice'))

    def _action_open_visit_invoices(self, invoices):
        action = {
            'name': _('Patient Invoices'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'context': {'default_move_type': 'out_invoice', 'default_partner_id': self.patient_id.id},
        }
        if len(invoices) == 1:
            action.update({'view_mode': 'form', 'res_id': invoices.id})
        else:
            action.update({'view_mode': 'list,form', 'domain': [('id', 'in', invoices.ids)]})
        return action

    def action_complete(self):
        res = super().action_complete()
        # Visits finished without a clinical case still get their consultation billed;
        # visits with a case are billed when the doctor completes the consultation.
        for appt in self.filtered(lambda a: a.state == 'completed' and not a.case_id):
            if (appt.branch_id or self.env.company).dental_auto_invoice:
                try:
                    with self.env.cr.savepoint():
                        appt.sudo()._create_visit_invoice()
                except UserError as err:
                    appt.message_post(body=_("Automatic invoice skipped: %s", err.args[0] if err.args else err))
        return res

    def _find_case_to_continue(self):
        """The patient's latest still-active case (same doctor first), within the user's access rules."""
        self.ensure_one()
        cases = self.env['dental.case'].search([
            ('patient_id', '=', self.patient_id.id),
            ('state', 'in', ('draft', 'open', 'under_treatment')),
        ], order='case_date desc, id desc')
        return cases.filtered(lambda c: c.doctor_id == self.doctor_id)[:1] or cases[:1]

    def _continue_case(self, case):
        """Attach this follow-up visit to an existing case and open its consultation record for today."""
        self.ensure_one()
        self.case_id = case
        if case.state in ('completed', 'cancelled'):
            # A booked review of a closed case reopens it for this visit
            case.state = 'open'
        exam_obj = self.env['dental.clinical.examination']
        if not exam_obj.search_count([('appointment_id', '=', self.id)]):
            exam_obj.create({
                'patient_id': self.patient_id.id,
                'case_id': case.id,
                'appointment_id': self.id,
                'doctor_id': self.doctor_id.id,
                'chief_complaint': self.env['dental.case']._extract_chief_complaint_from_appointment(self) or False,
            })
            case.message_post(body=_("Follow-up visit %(visit)s on %(date)s continued in this case.",
                                     visit=self.name, date=self.date_start))

    def _create_clinical_case(self):
        self.ensure_one()
        CaseObj = self.env['dental.case']
        return CaseObj.create({
            'patient_id': self.patient_id.id,
            'doctor_id': self.doctor_id.id,
            'appointment_id': self.id,
            'branch_id': self.branch_id.id,
            'chief_complaint': CaseObj._extract_chief_complaint_from_appointment(self),
            'medical_history_summary': CaseObj._extract_medical_history_from_patient(self.patient_id) if self.patient_id else False,
            'allergies': CaseObj._extract_allergies_from_patient(self.patient_id) if self.patient_id else False,
            'current_medications': CaseObj._extract_medications_from_patient(self.patient_id) if self.patient_id else False,
            'dental_history_summary': CaseObj._extract_dental_history_from_patient(self.patient_id) if self.patient_id else False,
        })

    def _action_open_case_form(self, case):
        action = self.env['ir.actions.act_window']._for_xml_id('dental_core.action_dental_case')
        action['res_id'] = case.id
        action['views'] = [(self.env.ref('dental_core.view_dental_case_form').id, 'form')]
        action['context'] = {'dental_current_visit_id': self.id}
        return action

    def action_open_visit_case(self):
        """Open the clinical case of a past visit (read-back from another case's Overview cards),
        showing that visit's own examination and records."""
        self.ensure_one()
        if not self.case_id:
            raise UserError(_("Visit %s has no clinical case.", self.name))
        return self._action_open_case_form(self.case_id)

    def action_new_clinical_case(self):
        """Open a separate case for an unrelated new problem instead of continuing the existing one."""
        self.ensure_one()
        old_case = self.case_id
        if old_case and old_case.appointment_id == self:
            raise UserError(_("This visit already has its own case %s.", old_case.name))
        if self.state in ('confirmed', 'checked_in'):
            # Start the consultation without the automatic case continuation of action_start_consultation
            super(DentalAppointment, self).action_start_consultation()
        case = self.with_context(dental_new_case_for_visit=True)._create_clinical_case()
        if old_case:
            # Today's consultation record moves with the visit
            self.env['dental.clinical.examination'].search([('appointment_id', '=', self.id)]).write({'case_id': case.id})
            old_case.message_post(body=_("Visit %(visit)s moved to new case %(case)s.", visit=self.name, case=case.name))
        self.case_id = case
        return self._action_open_case_form(case)

    def action_open_clinical_case(self):
        self.ensure_one()
        CaseObj = self.env['dental.case']
        if not self.case_id:
            # Returning patient: continue the open case instead of creating a duplicate
            case = self._find_case_to_continue()
            if case:
                self._continue_case(case)
                return self._action_open_case_form(case)
            case = self._create_clinical_case()
            self.case_id = case
            return self._action_open_case_form(case)
        if self.case_id.appointment_id != self:
            # Visit booked as a follow-up of this case (e.g. from a follow-up record)
            self._continue_case(self.case_id)
            return self._action_open_case_form(self.case_id)
        if self.case_id:
            # Open existing case
            case = self.case_id
            # Backfill any empty medical history / chief complaints from appointment and patient
            vals_to_update = {}
            if not case.chief_complaint:
                cc = CaseObj._extract_chief_complaint_from_appointment(self)
                if cc:
                    vals_to_update['chief_complaint'] = cc
            if self.patient_id:
                if not case.medical_history_summary:
                    med = CaseObj._extract_medical_history_from_patient(self.patient_id)
                    if med:
                        vals_to_update['medical_history_summary'] = med
                if not case.allergies:
                    allergies = CaseObj._extract_allergies_from_patient(self.patient_id)
                    if allergies:
                        vals_to_update['allergies'] = allergies
                if not case.current_medications:
                    meds = CaseObj._extract_medications_from_patient(self.patient_id)
                    if meds:
                        vals_to_update['current_medications'] = meds
                if not case.dental_history_summary:
                    dh = CaseObj._extract_dental_history_from_patient(self.patient_id)
                    if dh:
                        vals_to_update['dental_history_summary'] = dh
            if vals_to_update:
                case.write(vals_to_update)
            return self._action_open_case_form(case)

    @api.model
    def _dental_day_domain(self, utc_start, utc_end):
        """Appointments that belong to a clinic day: booked for it, or checked in on it.

        A patient who arrives on a different day than booked (early/late, or a
        booking made for the wrong date) is part of today's live queue as soon as
        the front desk checks them in.
        """
        return ['|',
                '&', ('date_start', '>=', utc_start), ('date_start', '<=', utc_end),
                '&', ('check_in_time', '>=', utc_start), ('check_in_time', '<=', utc_end)]

    def action_start_consultation(self):
        res = super().action_start_consultation()
        if len(self) == 1:
            return self.action_open_clinical_case()
        return res

    @api.model
    def get_admin_dashboard_data(self, branch_id=None):
        """
        Fetches live operational, clinical, and statistical data for the 
        Executive Dental Hospital Admin Dashboard.
        """
        company = self.env['res.company'].browse(branch_id) if branch_id else self.env.company
        self.env['dental.company.mixin']._dental_check_company_access(company)
        today = fields.Date.today()
        user_tz = pytz.timezone(self.env.user.tz or 'UTC')

        # Local start/end of today in UTC
        start_local = user_tz.localize(datetime.combine(today, time.min))
        end_local = user_tz.localize(datetime.combine(today, time.max))
        utc_start = start_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        utc_end = end_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')

        # Domain filters
        appt_domain = [
            ('date_start', '>=', utc_start),
            ('date_start', '<=', utc_end),
            ('branch_id', '=', company.id)
        ]

        # 1. Appointments counts
        appts_today = self.search(appt_domain, order='date_start asc')
        total_appts_today = len(appts_today)

        # In consultation / chairs
        in_consultation_count = sum(1 for a in appts_today if a.state == 'in_consultation')
        checked_in_count = sum(1 for a in appts_today if a.state == 'checked_in')
        completed_count = sum(1 for a in appts_today if a.state == 'completed')
        cancelled_count = sum(1 for a in appts_today if a.state == 'cancelled')

        # Follow-ups (Pending followups for clinic)
        followups_count = 0
        try:
            followups_count = self.env['dental.follow.up'].search_count([
                ('company_id', '=', company.id),
                ('state', '=', 'pending'),
                ('date', '<=', today)
            ])
        except Exception:
            pass
        if followups_count == 0:
            followups_count = sum(1 for a in appts_today if 'follow' in (a.reason or '').lower() or (a.treatment_id and 'follow' in (a.treatment_id.name or '').lower()))

        # 2. Patients (New & Total created today)
        new_patients_today = self.env['res.partner'].search_count([
            ('is_dental_patient', '=', True),
            ('create_date', '>=', utc_start),
            ('create_date', '<=', utc_end),
        ])

        # 3. Clinical Cases
        active_clinical_cases = self.env['dental.case'].search_count([
            ('state', 'in', ['open', 'under_treatment']),
            ('branch_id', '=', company.id)
        ])

        # 4. Prescriptions today
        prescriptions_count = 0
        try:
            prescriptions_count = self.env['dental.prescription'].search_count([
                ('company_id', '=', company.id),
                '|',
                ('prescription_date', '=', today),
                ('create_date', '>=', utc_start)
            ])
        except Exception:
            pass

        # 5. Lab Tests today
        lab_orders_count = 0
        try:
            lab_orders_count = self.env['dental.lab.order'].search_count([
                ('company_id', '=', company.id),
                '|',
                ('order_date', '=', today),
                ('create_date', '>=', utc_start)
            ])
        except Exception:
            pass

        # 6. Radiology (X-Ray) Today
        xray_count = self.env['ir.attachment'].search_count([
            ('res_model', 'in', ['dental.case', 'dental.clinical.examination', 'dental.treatment.plan', 'res.partner']),
            '|',
            ('mimetype', 'like', 'image%'),
            ('name', 'ilike', '%x-ray%')
        ])

        # Total OPD Visits today
        opd_visits_count = total_appts_today
        display_total_appts = total_appts_today

        # Chairs capacity
        total_chairs = getattr(company, 'dental_chair_count', 0) or 16
        occupied_chairs = min(in_consultation_count, total_chairs)
        chairs_occupancy_pct = int((occupied_chairs / total_chairs) * 100) if total_chairs > 0 else 0

        # Today's appointments list formatted
        appointments_list = []
        status_map = {
            'checked_in': {'label': 'Checked In', 'class': 'badge-checked-in'},
            'waiting': {'label': 'Waiting', 'class': 'badge-waiting'},
            'in_consultation': {'label': 'Ongoing', 'class': 'badge-ongoing'},
            'confirmed': {'label': 'Scheduled', 'class': 'badge-scheduled'},
            'pending': {'label': 'Scheduled', 'class': 'badge-scheduled'},
            'completed': {'label': 'Completed', 'class': 'badge-completed'},
            'cancelled': {'label': 'Cancelled', 'class': 'badge-cancelled'},
        }

        if appts_today:
            for a in appts_today[:8]:
                appt_time = fields.Datetime.context_timestamp(self, a.date_start).strftime('%H:%M') if a.date_start else ''
                st = a.state or 'confirmed'
                st_info = status_map.get(st, {'label': st.replace('_', ' ').title(), 'class': 'badge-scheduled'})
                t_name = a.treatment_id.name if a.treatment_id else (a.reason or 'Consultation')
                if isinstance(t_name, dict):
                    t_name = t_name.get('en_US', 'Consultation')
                appointments_list.append({
                    'id': a.id,
                    'time': appt_time,
                    'patient_id': a.patient_id.id,
                    'patient_name': a.patient_id.name,
                    'treatment': t_name,
                    'state': st,
                    'status_label': st_info['label'],
                    'status_class': st_info['class'],
                    'doctor_name': a.doctor_id.name or 'Dentist'
                })

        # Recent Patients (Real records from DB)
        recent_patients_list = []
        recent_partners = self.env['res.partner'].search(
            [('is_dental_patient', '=', True)],
            order='create_date desc, id desc',
            limit=5
        )

        for p in recent_partners:
            time_str = fields.Datetime.context_timestamp(self, p.create_date).strftime('%d %b %H:%M') if p.create_date else ''
            recent_patients_list.append({
                'id': p.id,
                'name': p.name,
                'treatment': 'Dental Patient',
                'time': time_str,
                'badge': 'Patient'
            })

        # Branches
        all_branches = [{'id': c.id, 'name': c.name} for c in self.env['res.company'].search([])]

        # Date string
        now_dt = fields.Date.today()
        weekday_name = now_dt.strftime('%a')
        month_name = now_dt.strftime('%b')
        formatted_date = f"{weekday_name}, {now_dt.day} {month_name} {now_dt.year}"

        # Real comparison vs yesterday for trend percentages
        yesterday = today - timedelta(days=1)
        yest_s = user_tz.localize(datetime.combine(yesterday, time.min)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        yest_e = user_tz.localize(datetime.combine(yesterday, time.max)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        yest_appts = self.search_count([('date_start', '>=', yest_s), ('date_start', '<=', yest_e), ('branch_id', '=', company.id)])

        def calc_trend(curr, prev):
            if prev > 0:
                pct = round(abs((curr - prev) / prev) * 100)
                d = 'up' if curr >= prev else 'down'
                return pct, d
            return 0, 'up'

        appts_trend_pct, appts_trend_dir = calc_trend(total_appts_today, yest_appts)

        # Real 6-day historical sparklines from database
        six_days_ago = today - timedelta(days=5)
        appt_sparkline = []
        rx_sparkline = []
        lab_sparkline = []
        rad_sparkline = []
        for i in range(6):
            cur_d = six_days_ago + timedelta(days=i)
            cur_s = user_tz.localize(datetime.combine(cur_d, time.min)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
            cur_e = user_tz.localize(datetime.combine(cur_d, time.max)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
            c_app = self.search_count([('date_start', '>=', cur_s), ('date_start', '<=', cur_e), ('branch_id', '=', company.id)])
            appt_sparkline.append(c_app)
            try:
                c_rx = self.env['dental.prescription'].search_count([
                    ('company_id', '=', company.id),
                    ('prescription_date', '=', cur_d)
                ])
            except Exception:
                c_rx = 0
            rx_sparkline.append(c_rx)
            try:
                c_lab = self.env['dental.lab.order'].search_count([
                    ('company_id', '=', company.id),
                    ('order_date', '=', cur_d)
                ])
            except Exception:
                c_lab = 0
            lab_sparkline.append(c_lab)
            c_rad = self.env['ir.attachment'].search_count([
                ('res_model', 'in', ['dental.case', 'dental.clinical.examination', 'dental.treatment.plan', 'res.partner']),
                ('create_date', '>=', cur_s),
                ('create_date', '<=', cur_e),
                '|', ('mimetype', 'like', 'image%'), ('name', 'ilike', '%x-ray%')
            ])
            rad_sparkline.append(c_rad)

        # Real hourly distribution from today's appointments
        hourly_slots = [
            {'hour': '8AM', 'start': 8, 'end': 10, 'count': 0},
            {'hour': '10AM', 'start': 10, 'end': 12, 'count': 0},
            {'hour': '12PM', 'start': 12, 'end': 14, 'count': 0},
            {'hour': '2PM', 'start': 14, 'end': 16, 'count': 0},
            {'hour': '4PM', 'start': 16, 'end': 18, 'count': 0},
            {'hour': '6PM', 'start': 18, 'end': 20, 'count': 0},
        ]
        for a in appts_today:
            if a.date_start:
                a_local = pytz.utc.localize(a.date_start).astimezone(user_tz)
                h = a_local.hour
                for s in hourly_slots:
                    if s['start'] <= h < s['end']:
                        s['count'] += 1
                        break

        hourly_points = [{'hour': s['hour'], 'count': s['count']} for s in hourly_slots]
        max_slot = max(hourly_slots, key=lambda s: s['count'])
        peak_time = f"{max_slot['hour'].replace('AM', ':00 AM').replace('PM', ':00 PM')}" if max_slot['count'] > 0 else '—'
        peak_count = max_slot['count']

        unread_notifs = self.env['mail.activity'].search_count([
            ('user_id', '=', self.env.uid),
            ('date_deadline', '<=', today)
        ])

        return {
            'header': {
                'clinic_name': company.name or 'Dental Hospital',
                'current_branch_id': company.id,
                'current_branch_name': company.name or 'Main Branch',
                'branches': all_branches,
                'user_name': self.env.user.name or 'Admin',
                'user_initial': (self.env.user.name or 'A')[0].upper(),
                'unread_notifications': unread_notifs,
                'date_str': formatted_date,
            },
            'floorplan': {
                'opd': {'count': opd_visits_count, 'capacity': 24, 'status': 'normal'},
                'chairs': {'occupied': occupied_chairs, 'total': total_chairs, 'status': 'normal'},
                'radiology': {'count': min(xray_count, 4), 'capacity': 4, 'status': 'normal'},
                'lab': {'count': min(lab_orders_count, 6), 'capacity': 6, 'status': 'warning' if lab_orders_count > 0 else 'normal'},
                'reception': {'waiting': checked_in_count, 'label': f"{checked_in_count} Waiting", 'status': 'info'},
                'clinical': {'active': active_clinical_cases, 'capacity': 8, 'status': 'normal'},
                'pharmacy': {'status': 'Active', 'count': prescriptions_count},
                'sterilization': {'status': 'Active'},
            },
            'kpis': {
                'opd_patients': {
                    'val': opd_visits_count,
                    'trend_pct': appts_trend_pct,
                    'trend_label': 'vs yesterday',
                    'trend_dir': appts_trend_dir,
                    'sparkline': appt_sparkline
                },
                'appointments': {
                    'val': display_total_appts,
                    'trend_pct': appts_trend_pct,
                    'trend_label': 'vs yesterday',
                    'trend_dir': appts_trend_dir,
                    'sparkline': appt_sparkline
                },
                'chairs_occupancy': {
                    'pct': chairs_occupancy_pct,
                    'occupied': occupied_chairs,
                    'total': total_chairs,
                    'label': f"{occupied_chairs} / {total_chairs} chairs in use"
                },
                'prescriptions': {
                    'val': prescriptions_count,
                    'trend_pct': 0,
                    'trend_label': 'vs yesterday',
                    'trend_dir': 'up',
                    'sparkline': rx_sparkline
                },
                'lab_tests': {
                    'val': lab_orders_count,
                    'trend_pct': 0,
                    'trend_label': 'vs yesterday',
                    'trend_dir': 'up',
                    'sparkline': lab_sparkline
                },
                'radiology': {
                    'val': xray_count,
                    'trend_pct': 0,
                    'trend_label': 'vs yesterday',
                    'trend_dir': 'up',
                    'sparkline': rad_sparkline
                }
            },
            'patient_flow': {
                'filter': 'Today',
                'peak_time': peak_time,
                'peak_count': peak_count,
                'opd_visits': opd_visits_count,
                'new_patients': new_patients_today,
                'follow_ups': followups_count,
                'cancellations': cancelled_count,
                'hourly_points': hourly_points
            },
            'today_appointments': appointments_list[:5],
            'recent_patients': recent_patients_list[:5]
        }

    def action_call_patient(self):
        for record in self:
            record.write({
                'called_time': fields.Datetime.now(),
            })
        return True

    @api.model
    def get_reception_dashboard_data(self, branch_id=None):
        company = self.env['res.company'].browse(branch_id) if branch_id else self.env.company
        self.env['dental.company.mixin']._dental_check_company_access(company)
        user_tz = pytz.timezone(self.env.user.tz or 'Asia/Kolkata')
        # Clinic-local date (server date is UTC and lags 5:30h behind in India)
        today = datetime.now(user_tz).date()

        # Local day boundaries in UTC
        start_local = user_tz.localize(datetime.combine(today, time.min))
        end_local = user_tz.localize(datetime.combine(today, time.max))
        utc_start = start_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        utc_end = end_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')

        # 1. Real appointments today
        domain = self._dental_day_domain(utc_start, utc_end)
        if branch_id:
            domain.append(('branch_id', '=', company.id))

        appts = self.search(domain, order='date_start asc')
        total_today = len(appts)

        checked_in_appts = appts.filtered(lambda a: a.state == 'checked_in')
        in_consultation_appts = appts.filtered(lambda a: a.state == 'in_consultation')
        completed_appts = appts.filtered(lambda a: a.state == 'completed')
        scheduled_appts = appts.filtered(lambda a: a.state in ['pending', 'confirmed'])

        checked_in_count = len(checked_in_appts)
        waiting_count = len(checked_in_appts)
        arrivals_count = len(checked_in_appts) + len(in_consultation_appts) + len(completed_appts)

        # 2. Real new patients created today
        new_registrations = self.env['res.partner'].search_count([
            ('is_dental_patient', '=', True),
            ('create_date', '>=', utc_start),
            ('create_date', '<=', utc_end),
        ])

        # 3. Real follow-ups due
        follow_ups_count = 0
        try:
            follow_ups_count = self.env['dental.follow.up'].search_count([
                ('company_id', '=', company.id),
                ('state', '=', 'pending'),
                ('date', '<=', today)
            ])
        except Exception:
            pass

        # 4. Real patients needing registration among today's visitors
        today_patient_ids = appts.mapped('patient_id').ids
        needs_registration_count = 0
        if today_patient_ids:
            needs_registration_count = self.env['res.partner'].search_count([
                ('id', 'in', today_patient_ids),
                '|', '|',
                ('dental_patient_id', '=', False),
                ('dental_patient_id', '=', 'New'),
                ('dental_patient_id', '=', '')
            ])

        # 5. Live Patient Queue list
        # Highest priority (emergencies) first, then first come, first served
        active_waiting = checked_in_appts.sorted(
            key=lambda a: (-(a.queue_priority or 0), a.check_in_time or a.date_start)
        )
        active_in_consult = in_consultation_appts.sorted(key=lambda a: a.date_start)
        upcoming_scheduled = scheduled_appts.sorted(key=lambda a: a.date_start)

        all_queue_appts = list(active_waiting) + list(active_in_consult) + list(upcoming_scheduled)

        next_token = "—"
        if active_waiting and active_waiting[0].token_number:
            next_token = active_waiting[0].token_number
        elif upcoming_scheduled and upcoming_scheduled[0].token_number:
            next_token = upcoming_scheduled[0].token_number

        queue_list = []
        for idx, a in enumerate(all_queue_appts[:15]):
            tok = a.token_number or a.name or f"#{idx+1}"

            start_utc = pytz.utc.localize(a.date_start)
            start_user = start_utc.astimezone(user_tz)
            time_display = start_user.strftime('%I:%M %p')

            treatment_title = 'Consultation'
            if a.treatment_id:
                tname = a.treatment_id.name
                if isinstance(tname, dict):
                    treatment_title = tname.get('en_US') or list(tname.values())[0]
                else:
                    treatment_title = str(tname)
            elif a.reason:
                treatment_title = a.reason

            # Real state and action mapping:
            if a.state == 'checked_in':
                if idx == 0 and active_waiting and a.id == active_waiting[0].id:
                    status_key = 'next'
                    status_label = 'Next'
                    badge_class = 'badge-next'
                    action_type = 'call_now'
                    action_label = 'Call Now'
                else:
                    status_key = 'checked_in'
                    status_label = 'Checked In'
                    badge_class = 'badge-checked-in'
                    action_type = 'start_visit'
                    action_label = 'Start Visit'
            elif a.state == 'in_consultation':
                status_key = 'in_consultation'
                status_label = 'In Consultation'
                badge_class = 'badge-consultation'
                action_type = 'start_visit'
                action_label = 'In Visit'
            elif a.state in ['confirmed', 'pending']:
                status_key = 'waiting'
                status_label = 'Scheduled' if a.state == 'pending' else 'Confirmed'
                badge_class = 'badge-waiting'
                action_type = 'check_in'
                action_label = 'Check In'
            elif a.state == 'completed':
                status_key = 'completed'
                status_label = 'Completed'
                badge_class = 'badge-checked-in'
                action_type = 'manage'
                action_label = 'Manage'
            else:
                status_key = 'other'
                status_label = a.state.capitalize()
                badge_class = 'badge-waiting'
                action_type = 'manage'
                action_label = 'Manage'

            queue_list.append({
                'id': a.id,
                'index': idx + 1,
                'token': tok,
                'patient_id': a.patient_id.id,
                'patient_name': a.patient_id.name or 'Unknown',
                'patient_phone': a.patient_id.phone or '',
                'appointment_info': f"{treatment_title} {time_display}",
                'treatment_name': treatment_title,
                'time_display': time_display,
                'state': a.state,
                'status_key': status_key,
                'status_label': status_label,
                'badge_class': badge_class,
                'action_type': action_type,
                'action_label': action_label,
                'has_equipment_conflict': bool(a.has_equipment_conflict),
                'equipment_conflict_reason': a.equipment_conflict_reason or '',
                'conflicting_equipment_names': ", ".join(a.conflicting_equipment_ids.mapped('name')) if a.conflicting_equipment_ids else '',
                'is_scrapped_conflict': bool(
                    a.conflicting_equipment_ids.filtered(
                        lambda e: e.equipment_condition == 'scrapped' or getattr(e, 'scrap_date', False) or e.maintenance_ids.filtered(lambda r: r.stage_id and 'scrap' in (r.stage_id.name or '').lower())
                    )
                ),
            })

        # 6. Real Today's Appointments Timeline
        timeline_list = []
        for a in appts:
            start_utc = pytz.utc.localize(a.date_start)
            start_user = start_utc.astimezone(user_tz)
            time_display = start_user.strftime('%I:%M %p')

            treatment_title = 'Consultation'
            if a.treatment_id:
                tname = a.treatment_id.name
                if isinstance(tname, dict):
                    treatment_title = tname.get('en_US') or list(tname.values())[0]
                else:
                    treatment_title = str(tname)
            elif a.reason:
                treatment_title = a.reason

            if a.state == 'completed':
                status_label = 'Completed'
                status_class = 'status-completed'
                dot_class = 'dot-completed'
            elif a.state == 'checked_in':
                status_label = 'Checked In'
                status_class = 'status-checked-in'
                dot_class = 'dot-checked-in'
            elif a.state == 'in_consultation':
                status_label = 'In Consultation'
                status_class = 'status-consultation'
                dot_class = 'dot-consultation'
            else:
                status_label = 'Scheduled' if a.state == 'pending' else 'Confirmed'
                status_class = 'status-scheduled'
                dot_class = 'dot-scheduled'

            timeline_list.append({
                'id': a.id,
                'time_display': time_display,
                'patient_id': a.patient_id.id,
                'patient_name': a.patient_id.name or 'Unknown',
                'treatment_name': treatment_title,
                'state': a.state,
                'status_label': status_label,
                'status_class': status_class,
                'dot_class': dot_class,
            })

        # 7. Doctors Availability for Reception Desk
        all_dentists = self.env['hr.employee'].sudo().search([
            ('is_dentist', '=', True), ('active', '=', True), ('company_id', 'in', [False, company.id]),
        ], order='id asc')
        now_utc = fields.Datetime.now()
        doctors_availability = []
        for doc in all_dentists:
            avatar = f'/web/image?model=hr.employee&field=avatar_128&id={doc.id}'

            # Check approved leave
            on_leave = self.env['hr.leave'].sudo().search([
                ('employee_id', '=', doc.id),
                ('state', '=', 'validate'),
                ('date_from', '<=', now_utc),
                ('date_to', '>=', now_utc),
            ], limit=1)

            # Check active consultation right now
            in_consult = appts.filtered(lambda a: a.doctor_id.id == doc.id and a.state == 'in_consultation')
            # Doctor's appointments today
            doc_appts = appts.filtered(lambda a: a.doctor_id.id == doc.id)

            if on_leave:
                status_code = 'on_leave'
                status_label = 'On Leave'
                badge_class = 'badge-leave'
            elif in_consult:
                status_code = 'busy'
                pat_name = in_consult[0].patient_id.name or 'Patient'
                status_label = f'In Visit ({pat_name.split()[0]})'
                badge_class = 'badge-busy'
            else:
                status_code = 'available'
                status_label = 'Available Now'
                badge_class = 'badge-available'

            doctors_availability.append({
                'id': doc.id,
                'name': doc.name,
                'specialization': doc.specialization or 'Dentist',
                'avatar_url': avatar,
                'status_code': status_code,
                'status_label': status_label,
                'badge_class': badge_class,
                'today_appointments': len(doc_appts),
                'phone': doc.work_phone or '',
            })

        # 8. Real CRM Enquiries & Follow-ups for Reception Desk
        crm_domain = [('active', '=', True), ('type', 'in', ('opportunity', 'lead'))]
        if branch_id:
            crm_domain.append(('company_id', 'in', [company.id, False]))

        open_leads = self.env['crm.lead'].search(crm_domain, order='create_date desc, id desc')
        new_enquiries = open_leads.filtered(lambda l: l.conversion_status == 'new' or (not l.appointment_id and l.conversion_status == 'contacted'))
        new_enquiries_count = len(new_enquiries)
        total_open_enquiries = len(open_leads.filtered(lambda l: (not l.stage_id or not l.stage_id.is_won) and l.conversion_status != 'cancelled'))

        # Enquiries converted into real appointments
        converted_enquiries = open_leads.filtered(lambda l: l.appointment_id or l.conversion_status in ('appointment_scheduled', 'appointment_completed'))
        converted_appointments_count = len(converted_enquiries)

        # Scheduled follow-up activities due or overdue
        today_date = today
        lead_activities = self.env['mail.activity'].search([
            ('res_model', '=', 'crm.lead'),
            ('res_id', 'in', open_leads.ids),
            ('date_deadline', '<=', today_date)
        ]) if open_leads else self.env['mail.activity'].browse()
        due_followup_lead_ids = set(lead_activities.mapped('res_id'))
        crm_followups_due_count = len(open_leads.filtered(lambda l: l.id in due_followup_lead_ids or l.conversion_status == 'follow_up'))

        # Total combined follow-ups
        combined_followups = follow_ups_count + crm_followups_due_count

        # Sources Breakdown
        source_breakdown = {
            'Website': 0,
            'Phone Call': 0,
            'Walk-in': 0,
            'Patient Referral': 0,
            'Social Media': 0,
            'Other': 0,
        }
        for lead in open_leads:
            st = lead.source_type or ''
            sname = (lead.source_id.name or '').lower() if lead.source_id else ''
            if st == 'website' or 'web' in sname:
                source_breakdown['Website'] += 1
            elif st == 'phone' or 'phone' in sname:
                source_breakdown['Phone Call'] += 1
            elif st == 'walk_in' or 'walk' in sname:
                source_breakdown['Walk-in'] += 1
            elif st == 'referral' or 'refer' in sname:
                source_breakdown['Patient Referral'] += 1
            elif st in ('facebook', 'instagram') or 'facebook' in sname or 'instagram' in sname:
                source_breakdown['Social Media'] += 1
            else:
                source_breakdown['Other'] += 1

        # Format recent enquiries for live reception desk table
        source_labels = {
            'walk_in': ('Walk-in', 'badge-walkin'),
            'phone': ('Phone Call', 'badge-phone'),
            'website': ('Website', 'badge-website'),
            'referral': ('Referral', 'badge-referral'),
            'facebook': ('Facebook', 'badge-social'),
            'instagram': ('Instagram', 'badge-social'),
            'google': ('Google Search', 'badge-website'),
            'other': ('Other', 'badge-other'),
        }
        conv_labels = {
            'new': ('New Enquiry', 'status-new'),
            'contacted': ('Contacted', 'status-contacted'),
            'follow_up': ('Follow-up Due', 'status-followup'),
            'appointment_scheduled': ('Appt Booked', 'status-scheduled'),
            'appointment_completed': ('Completed', 'status-completed'),
            'cancelled': ('Cancelled', 'status-cancelled'),
        }

        crm_enquiries = []
        for l in open_leads[:50]:
            treatment_title = '—'
            if l.treatment_id:
                tname = l.treatment_id.name
                treatment_title = (tname.get('en_US') or list(tname.values())[0]) if isinstance(tname, dict) else str(tname)
            elif l.name:
                treatment_title = l.name

            doc_name = l.preferred_doctor_id.name if l.preferred_doctor_id else '—'
            next_act = l.activity_ids.sorted(key=lambda a: a.date_deadline)[:1]
            act_summary = next_act.summary or (next_act.activity_type_id.name if next_act else '')
            act_date_str = next_act.date_deadline.strftime('%d %b') if next_act and next_act.date_deadline else ''
            act_status = 'none'
            if next_act and next_act.date_deadline:
                if next_act.date_deadline < today_date:
                    act_status = 'overdue'
                elif next_act.date_deadline == today_date:
                    act_status = 'today'
                else:
                    act_status = 'planned'

            s_label, s_class = source_labels.get(l.source_type or '', (l.source_id.name if l.source_id else 'Enquiry', 'badge-other'))
            conv_status = l.conversion_status or 'new'
            c_label, c_class = conv_labels.get(conv_status, ('Open', 'status-contacted'))
            resp_name = l.user_id.name if l.user_id else '—'

            rec_date_str = ''
            if l.create_date:
                utc_dt = pytz.utc.localize(l.create_date)
                local_dt = utc_dt.astimezone(user_tz)
                rec_date_str = local_dt.strftime('%d %b, %I:%M %p')

            crm_enquiries.append({
                'id': l.id,
                'name': l.name or '',
                'contact_name': l.contact_name or l.partner_name or (l.patient_id.name if l.patient_id else False) or l.name or '—',
                'phone': l.phone or (l.patient_id.phone if l.patient_id else False) or '',
                'email': l.email_from or (l.patient_id.email if l.patient_id else False) or '',
                'source_type': l.source_type or 'other',
                'source_label': s_label,
                'source_class': s_class,
                'treatment_name': treatment_title,
                'doctor_name': doc_name,
                'user_name': resp_name,
                'stage_name': l.stage_id.name if l.stage_id else 'New',
                'conversion_status': conv_status,
                'conversion_label': c_label,
                'conversion_class': c_class,
                'activity_summary': act_summary,
                'activity_date': act_date_str,
                'activity_status': act_status,
                'has_matching_patient': l.has_matching_patient,
                'matching_patient_id': l.matching_patient_id.id if l.matching_patient_id else False,
                'matching_patient_name': l.matching_patient_id.name if l.matching_patient_id else False,
                'patient_id': l.patient_id.id if l.patient_id else False,
                'patient_name': l.patient_id.name if l.patient_id else False,
                'appointment_id': l.appointment_id.id if l.appointment_id else False,
                'appointment_name': l.appointment_id.name if l.appointment_id else False,
                'appointment_state': l.appointment_id.state if l.appointment_id else False,
                'received_date': rec_date_str,
            })

        # 8. Equipment under maintenance or unavailable in this branch (with Scrap Stage tracking)
        equip_domain = ['|', ('company_id', '=', False), ('company_id', '=', company.id)]
        branch_equipments = self.env['maintenance.equipment'].search(equip_domain)

        # Find maintenance requests on branch equipment
        all_reqs = self.env['maintenance.request'].sudo().search([
            ('equipment_id', 'in', branch_equipments.ids)
        ])
        scrap_reqs = all_reqs.filtered(lambda r: r.stage_id and ('scrap' in (r.stage_id.name or '').lower() or 'decommission' in (r.stage_id.name or '').lower()))
        scrapped_equip_ids = set(scrap_reqs.mapped('equipment_id.id'))

        open_repair_reqs = all_reqs.filtered(lambda r: not r.stage_id.fold and r.equipment_availability_impact in ('unavailable', 'reduced_capacity'))
        repair_equip_ids = set(open_repair_reqs.mapped('equipment_id.id'))

        scrapped_equips = branch_equipments.filtered(
            lambda e: e.id in scrapped_equip_ids or
                      getattr(e, 'equipment_condition', '') == 'scrapped' or
                      bool(getattr(e, 'scrap_date', False))
        )
        # Ensure condition is synced in DB if missing
        for sq in scrapped_equips:
            if sq.equipment_condition != 'scrapped' or sq.is_available:
                sq.sudo().write({'equipment_condition': 'scrapped', 'is_available': False})

        maintenance_equips = branch_equipments.filtered(
            lambda e: e.id not in scrapped_equips.ids and (
                e.id in repair_equip_ids or
                (hasattr(e, 'is_available') and not e.is_available) or
                (hasattr(e, 'equipment_condition') and e.equipment_condition in ('under_repair', 'out_of_order', 'needs_maintenance'))
            )
        )

        unavailable_equips = scrapped_equips | maintenance_equips

        # Find today's and future appointments in this clinic to assess impact
        upcoming_appts = self.search([
            ('branch_id', '=', company.id),
            ('state', 'in', ('pending', 'confirmed', 'checked_in')),
            ('date_start', '>=', utc_start),
        ])

        scrapped_equipment = []
        for e in scrapped_equips:
            e_scrap_req = scrap_reqs.filtered(lambda r: r.equipment_id.id == e.id)[:1]
            scrap_reason = (e_scrap_req.name or e_scrap_req.description or '') if e_scrap_req else ''
            if scrap_reason and '<' in scrap_reason:
                import re
                scrap_reason = re.sub('<[^<]+?>', '', scrap_reason).strip()

            impacted = upcoming_appts.filtered(
                lambda a: e in a.appointment_type_id.required_equipment_ids or
                          (e.category_id and e.category_id in a.appointment_type_id.required_equipment_category_ids)
            )

            scrapped_equipment.append({
                'id': e.id,
                'name': e.name,
                'category_id': e.category_id.id if e.category_id else False,
                'category_name': e.category_id.name if e.category_id else 'General Equipment',
                'serial_no': e.serial_no or '',
                'scrap_date': e.scrap_date.strftime('%d %b %Y') if getattr(e, 'scrap_date', False) else '',
                'scrap_reason': scrap_reason or 'Equipment decommissioned & scrapped in maintenance module.',
                'request_id': e_scrap_req.id if e_scrap_req else False,
                'affected_appointments_count': len(impacted),
                'affected_appointment_ids': impacted.ids,
            })

        maintenance_equipment = []
        for e in maintenance_equips:
            e_rep_req = open_repair_reqs.filtered(lambda r: r.equipment_id.id == e.id)[:1]
            req_issue = (e_rep_req.name or '') if e_rep_req else ''
            stage_name = e_rep_req.stage_id.name if (e_rep_req and e_rep_req.stage_id) else (
                'Under Repair' if e.equipment_condition == 'under_repair' else 'Out of Order'
            )
            tech_name = e_rep_req.user_ids[:1].name if (e_rep_req and e_rep_req.user_ids) else (
                e.technician_user_id.name if e.technician_user_id else ''
            )

            impacted = upcoming_appts.filtered(
                lambda a: e in a.appointment_type_id.required_equipment_ids or
                          (e.category_id and e.category_id in a.appointment_type_id.required_equipment_category_ids)
            )

            maintenance_equipment.append({
                'id': e.id,
                'name': e.name,
                'category_id': e.category_id.id if e.category_id else False,
                'category_name': e.category_id.name if e.category_id else 'General Equipment',
                'serial_no': e.serial_no or '',
                'condition': getattr(e, 'equipment_condition', 'under_repair'),
                'stage_name': stage_name,
                'issue': req_issue or 'Reported defect / maintenance in progress',
                'technician_name': tech_name,
                'request_id': e_rep_req.id if e_rep_req else False,
                'affected_appointments_count': len(impacted),
                'affected_appointment_ids': impacted.ids,
            })

        unavailable_equipment = [{
            'id': e.id,
            'name': e.name,
            'category_name': e.category_id.name if e.category_id else 'Equipment',
            'condition': getattr(e, 'equipment_condition', 'under_repair'),
            'serial_no': e.serial_no or '',
        } for e in unavailable_equips]

        return {
            'stats': {
                'today_appointments': total_today,
                'waiting_patients': waiting_count,
                'checked_in_patients': checked_in_count,
                'new_patients_today': new_registrations,
                'upcoming_follow_ups': combined_followups,
                'arrivals': arrivals_count,
                'needs_registration': needs_registration_count,
                'next_token': next_token,
                'crm_new_enquiries': new_enquiries_count,
                'crm_open_enquiries': total_open_enquiries,
                'crm_pending_followups': crm_followups_due_count,
                'crm_converted_appointments': converted_appointments_count,
                'unavailable_equipment_count': len(unavailable_equipment),
                'scrapped_equipment_count': len(scrapped_equipment),
                'under_maintenance_count': len(maintenance_equipment),
            },
            'queue_list': queue_list,
            'can_start_consultation': self._can_start_consultation(),
            'can_check_in': self._can_check_in(),
            'timeline_list': timeline_list,
            'doctors_availability': doctors_availability,
            'crm_enquiries': crm_enquiries,
            'crm_source_breakdown': source_breakdown,
            'unavailable_equipment': unavailable_equipment,
            'scrapped_equipment': scrapped_equipment,
            'maintenance_equipment': maintenance_equipment,
        }

    @api.model
    def get_waiting_queue_board_data(self, branch_id=None):
        """
        Fetches structured real-time queue data per doctor operatory for
        the Reception Desk Waiting Queue Screen and Future TV Display Board.
        """
        company = self.env['res.company'].browse(branch_id) if branch_id else self.env.company
        self.env['dental.company.mixin']._dental_check_company_access(company)
        user_tz = pytz.timezone(self.env.user.tz or 'Asia/Kolkata')
        # Clinic-local date (server date is UTC and lags 5:30h behind in India)
        today = datetime.now(user_tz).date()

        # Local day boundaries in UTC
        start_local = user_tz.localize(datetime.combine(today, time.min))
        end_local = user_tz.localize(datetime.combine(today, time.max))
        utc_start = start_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        utc_end = end_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')

        # Clinic header info
        partner = company.partner_id
        clinic_name = company.name or "Dental Hospital & Surgical Center"
        address_parts = [p for p in [partner.street, partner.city, partner.zip] if p]
        clinic_address = ", ".join(address_parts) if address_parts else "Main Clinic & Dental Surgery"

        # 1. Real appointments today
        domain = self._dental_day_domain(utc_start, utc_end)
        if branch_id:
            domain.append(('branch_id', '=', company.id))

        today_appts = self.search(domain, order='date_start asc')
        total_patients_today = len(today_appts)
        now_serving_total = len(today_appts.filtered(lambda a: a.state == 'in_consultation'))
        waiting_total = len(today_appts.filtered(lambda a: a.state == 'checked_in'))
        completed_total = len(today_appts.filtered(lambda a: a.state == 'completed'))

        # Fetch active real doctors (strictly real doctors, no dummy records!)
        real_dentists = self.env['hr.employee'].sudo().search([
            ('is_dentist', '=', True),
            ('active', '=', True),
            ('company_id', 'in', [False, company.id]),
        ], order='id asc')

        # If any appointment has an assigned active employee who is acting as doctor, include them
        assigned_doc_ids = today_appts.mapped('doctor_id').ids
        extra_docs = self.env['hr.employee'].sudo().search([
            ('id', 'in', assigned_doc_ids),
            ('id', 'not in', real_dentists.ids),
            ('active', '=', True)
        ], order='id asc')
        all_active_doctors = real_dentists | extra_docs

        # Helper to format clean TV token
        def clean_token(appt, fallback_idx=1):
            raw = appt.token_number
            if raw:
                parts = raw.replace('/', '-').split('-')
                last_part = parts[-1]
                if last_part.isdigit():
                    return f"T-{int(last_part):03d}"
                return raw[:8].upper()
            assigned_tok = f"T-{appt.id % 1000:03d}" if appt.id else f"T-{fallback_idx:03d}"
            try:
                appt.sudo().write({'token_number': assigned_tok})
            except Exception:
                pass
            return assigned_tok

        # Helper to format demographic string e.g. (28F), (42M)
        def format_demographics(partner):
            if not partner:
                return ""
            parts = []
            age_val = getattr(partner, 'age', 0)
            if age_val and age_val > 0:
                parts.append(str(age_val))
            gender_val = getattr(partner, 'gender', False)
            if gender_val:
                g_code = 'M' if gender_val == 'male' else ('F' if gender_val == 'female' else 'O')
                if parts:
                    return f"({parts[0]}{g_code})"
                return f"({g_code})"
            elif parts:
                return f"({parts[0]}y)"
            return ""

        # Color palettes for operatories (modern clinic accents, bright and crisp)
        operatory_palettes = [
            {'name': 'Operatory 1', 'color': '#0284c7', 'bg_tint': '#f0f9ff', 'border': '#bae6fd'},
            {'name': 'Operatory 2', 'color': '#059669', 'bg_tint': '#ecfdf5', 'border': '#a7f3d0'},
            {'name': 'Operatory 3', 'color': '#d97706', 'bg_tint': '#fffbeb', 'border': '#fde68a'},
            {'name': 'Operatory 4', 'color': '#7c3aed', 'bg_tint': '#f5f3ff', 'border': '#ddd6fe'},
            {'name': 'Operatory 5', 'color': '#0891b2', 'bg_tint': '#ecfeff', 'border': '#a5f3fc'},
        ]

        doctors_data = []
        token_counter = 1

        for d_idx, doc in enumerate(all_active_doctors):
            palette = operatory_palettes[d_idx % len(operatory_palettes)]
            doc_appts = today_appts.filtered(lambda a: a.doctor_id.id == doc.id)

            spec = getattr(doc, 'specialization', False) or (doc.department_id.name if doc.department_id else 'Dental Surgeon')
            op_label = f"{spec} • {palette['name']}"

            # 1. Now Serving (in_consultation)
            in_consult = doc_appts.filtered(lambda a: a.state == 'in_consultation').sorted(
                key=lambda a: (a.called_time or a.date_start), reverse=True
            )
            now_serving = None
            if in_consult:
                curr = in_consult[0]
                t_tok = clean_token(curr, token_counter)
                token_counter += 1

                elapsed_mins = 0
                if curr.called_time:
                    diff = fields.Datetime.now() - curr.called_time
                    elapsed_mins = max(1, int(diff.total_seconds() / 60))

                now_serving = {
                    'id': curr.id,
                    'token': t_tok,
                    'raw_token': curr.token_number or t_tok,
                    'patient_id': curr.patient_id.id,
                    'patient_name': curr.patient_id.name or 'Unknown',
                    'demographics': format_demographics(curr.patient_id),
                    'treatment_name': curr._dentist_dashboard_treatment_title(),
                    'state': curr.state,
                    'elapsed_mins': elapsed_mins,
                }

            # 2. Waiting Queue (checked_in)
            # Queue Rules strictly applied:
            # 1. Emergency / queue_priority desc (Emergencies first)
            # 2. check_in_time asc (First-come, first-served)
            # 3. date_start asc
            waiting = doc_appts.filtered(lambda a: a.state == 'checked_in').sorted(
                key=lambda a: (
                    not a.is_emergency,
                    -(a.queue_priority or 0),
                    a.check_in_time or a.date_start or fields.Datetime.now(),
                    a.date_start or fields.Datetime.now()
                )
            )

            waiting_list = []
            for w_idx, w in enumerate(waiting):
                w_tok = clean_token(w, token_counter)
                token_counter += 1

                w_mins = 0
                if w.check_in_time:
                    diff = fields.Datetime.now() - w.check_in_time
                    w_mins = max(0, int(diff.total_seconds() / 60))

                waiting_list.append({
                    'id': w.id,
                    'token': w_tok,
                    'raw_token': w.token_number or w_tok,
                    'is_next': (w_idx == 0),
                    'patient_id': w.patient_id.id,
                    'patient_name': w.patient_id.name or 'Unknown',
                    'demographics': format_demographics(w.patient_id),
                    'treatment_name': w._dentist_dashboard_treatment_title(),
                    'waiting_mins': w_mins,
                    'is_emergency': bool(w.is_emergency or (w.queue_priority and w.queue_priority > 5)),
                })

            # 3. Upcoming Scheduled patients for this doctor today (confirmed/pending)
            upcoming = doc_appts.filtered(lambda a: a.state in ['confirmed', 'pending']).sorted(key=lambda a: a.date_start)
            upcoming_list = []
            for u in upcoming[:8]:
                u_tok = clean_token(u, token_counter)
                token_counter += 1
                start_utc = pytz.utc.localize(u.date_start)
                start_user = start_utc.astimezone(user_tz)
                time_display = start_user.strftime('%I:%M %p')

                upcoming_list.append({
                    'id': u.id,
                    'token': u_tok,
                    'patient_id': u.patient_id.id,
                    'patient_name': u.patient_id.name or 'Unknown',
                    'demographics': format_demographics(u.patient_id),
                    'scheduled_time': time_display,
                    'treatment_name': u._dentist_dashboard_treatment_title(),
                })

            doctors_data.append({
                'doctor_id': doc.id,
                'doctor_name': doc.name if doc.name.lower().startswith(('dr.', 'dr ')) else f"Dr. {doc.name}",
                'specialization': spec,
                'operatory_title': op_label,
                'operatory_name': palette['name'],
                'accent_color': palette['color'],
                'bg_tint': palette['bg_tint'],
                'border_color': palette['border'],
                'avatar_url': f'/web/image?model=hr.employee.public&field=avatar_128&id={doc.id}',
                'now_serving': now_serving,
                'waiting_queue': waiting_list,
                'upcoming_list': upcoming_list,
                'waiting_count': len(waiting_list),
                'completed_count': len(doc_appts.filtered(lambda a: a.state == 'completed')),
                'total_doc_patients': len(doc_appts),
            })

        return {
            'clinic_name': clinic_name,
            'clinic_address': clinic_address,
            'stats': {
                'total_patients_today': total_patients_today,
                'now_serving_count': now_serving_total,
                'waiting_count': waiting_total,
                'completed_count': completed_total,
            },
            'doctors': doctors_data,
            'can_start_consultation': self._can_start_consultation(),
            'can_check_in': self._can_check_in(),
        }

    # ---------------------------------------------------------
    # Dentist Dashboard
    # ---------------------------------------------------------
    DENTIST_STATUS_DISPLAY = {
        'pending': ('Pending', 'st-pending'),
        'confirmed': ('Confirmed', 'st-confirmed'),
        'checked_in': ('Waiting', 'st-waiting'),
        'in_consultation': ('In Chair', 'st-active'),
        'completed': ('Completed', 'st-done'),
        'cancelled': ('Cancelled', 'st-cancelled'),
        'no_show': ('No Show', 'st-cancelled'),
    }

    def action_dashboard_finish(self):
        """Finish a visit from the dentist dashboard.

        When a clinical case exists, completion goes through the case so its
        validations (e.g. chief complaint) are applied; otherwise the
        appointment is completed directly.
        """
        for appt in self:
            if appt.case_id:
                appt.case_id.with_context(dental_current_visit_id=appt.id).action_complete_consultation()
            else:
                appt.action_complete()
        return True

    def _dentist_dashboard_treatment_title(self):
        self.ensure_one()
        if self.treatment_id:
            return self.treatment_id.name
        if self.appointment_type_id:
            return self.appointment_type_id.name
        if self.reason:
            return self.reason.strip().splitlines()[0][:60]
        return _('Consultation')

    def _dentist_dashboard_row(self, user_tz, now_utc):
        self.ensure_one()
        label, css = self.DENTIST_STATUS_DISPLAY.get(self.state, (self.state, 'st-pending'))
        start_local = pytz.utc.localize(self.date_start).astimezone(user_tz)
        waiting_mins = 0
        if self.state == 'checked_in' and self.check_in_time:
            waiting_mins = max(0, int((now_utc - self.check_in_time).total_seconds() // 60))
        in_chair_mins = 0
        if self.state == 'in_consultation' and self.called_time:
            in_chair_mins = max(0, int((now_utc - self.called_time).total_seconds() // 60))
        check_in_display = ''
        if self.check_in_time:
            check_in_display = pytz.utc.localize(self.check_in_time).astimezone(user_tz).strftime('%I:%M %p').lstrip('0')
        patient_ref = self.patient_id.dental_patient_id
        return {
            'id': self.id,
            'name': self.name,
            'token': self.token_number or '',
            'patient_id': self.patient_id.id,
            'patient_name': self.patient_id.name or _('Patient'),
            'patient_ref': patient_ref if patient_ref and patient_ref != 'New' else '',
            'avatar_url': f'/web/image?model=res.partner&field=avatar_128&id={self.patient_id.id}',
            'treatment': self._dentist_dashboard_treatment_title(),
            'time': start_local.strftime('%I:%M %p').lstrip('0'),
            'check_in_time': check_in_display,
            'state': self.state,
            'status_label': label,
            'status_class': css,
            'is_emergency': self.is_emergency,
            'waiting_mins': waiting_mins,
            'in_chair_mins': in_chair_mins,
            'has_case': bool(self.case_id),
        }

    @api.model
    def get_dentist_dashboard_data(self, **kwargs):
        """
        Data for the Dentist Dashboard: the current user's own live clinic day
        (patient in chair, waiting queue, schedule), KPIs and the appointments
        overview chart.

        Strictly scoped to the employee linked to the current user with
        Dental Role = Dentist. No other doctor can be selected: any doctor id
        sent by the client is ignored, and users without such a profile get
        no clinical data at all.
        """
        user = self.env.user
        if not user._has_dentist_workspace_access():
            if not user.has_groups(DENTIST_WORKSPACE_GROUPS):
                raise AccessError(_("You are not allowed to access the Dentist Workspace."))
            # Dental permission but no linked Dentist employee: empty state only
            return {
                'has_doctor': False,
                'doctor_info': {
                    'id': False,
                    'name': user.name,
                    'display_name': user.name,
                    'greeting': _("Dentist Workspace"),
                    'specialization': _("No dentist profile"),
                    'branch_name': '',
                    'avatar_url': f'/web/image?model=res.users&field=avatar_128&id={user.id}',
                },
            }
        selected_doctor = user._get_dental_dentist_profile()

        today = fields.Date.context_today(self)
        user_tz = pytz.timezone(user.tz or 'Asia/Kolkata')
        now_utc = fields.Datetime.now()
        now_local = pytz.utc.localize(now_utc).astimezone(user_tz)

        def to_utc(local_date, t=time.min):
            return user_tz.localize(datetime.combine(local_date, t)).astimezone(pytz.utc).replace(tzinfo=None)

        utc_start = to_utc(today)
        utc_end = to_utc(today, time.max)

        doctor_domain = [('doctor_id', '=', selected_doctor.id)]
        active_states = ['pending', 'confirmed', 'checked_in', 'in_consultation', 'completed']

        # Today's appointments
        today_appts = self.search(doctor_domain + self._dental_day_domain(utc_start, utc_end), order='date_start asc')
        live_today = today_appts.filtered(lambda a: a.state in active_states)
        waiting = today_appts.filtered(lambda a: a.state == 'checked_in').sorted(
            key=lambda a: (not a.is_emergency, a.check_in_time or a.date_start)
        )
        completed_today = today_appts.filtered(lambda a: a.state == 'completed')
        remaining_today = today_appts.filtered(lambda a: a.state in ['pending', 'confirmed'])
        cancelled_today = today_appts.filtered(lambda a: a.state in ['cancelled', 'no_show'])

        # Patient currently in the chair (not limited to today so a forgotten visit stays visible)
        current = self.search(doctor_domain + [('state', '=', 'in_consultation')], order='called_time desc', limit=1)

        # First-visit patients among today's appointments (no earlier visit with any doctor)
        today_patients = live_today.mapped('patient_id')
        returning = today_patients.browse()
        if today_patients:
            returning = self.search([
                ('patient_id', 'in', today_patients.ids),
                ('date_start', '<', utc_start),
                ('state', 'in', active_states),
            ]).mapped('patient_id')
        new_patients_today = len(today_patients - returning)

        # Follow-ups due for this doctor
        followups_due = 0
        if selected_doctor:
            followups_due = self.env['dental.follow.up'].search_count([
                ('doctor_id', '=', selected_doctor.id),
                ('state', '=', 'pending'),
                ('date', '<=', today),
            ])

        # This month: distinct patients and value of completed treatments (at list price)
        month_appts = self.search(doctor_domain + [
            ('date_start', '>=', to_utc(today.replace(day=1))),
            ('date_start', '<=', utc_end),
            ('state', 'in', active_states),
        ])
        company = selected_doctor.company_id or self.env.company
        month_value = sum(a.treatment_id.list_price for a in month_appts if a.state == 'completed' and a.treatment_id)

        # Overview charts: one query over the needed range, bucketed by local date
        week_start = today - timedelta(days=today.weekday())
        range_start = min(date(today.year, 1, 1), week_start)
        range_end = max(date(today.year, 12, 31), week_start + timedelta(days=6))
        chart_rows = self.search_read(doctor_domain + [
            ('date_start', '>=', to_utc(range_start)),
            ('date_start', '<=', to_utc(range_end, time.max)),
            ('state', 'in', active_states),
        ], ['date_start'])
        per_day = {}
        for row in chart_rows:
            local_day = pytz.utc.localize(row['date_start']).astimezone(user_tz).date()
            per_day[local_day] = per_day.get(local_day, 0) + 1

        def hour_label(h):
            return f"{h % 12 or 12}{'a' if h < 12 else 'p'}"

        hour_counts = {}
        for a in live_today:
            h = pytz.utc.localize(a.date_start).astimezone(user_tz).hour
            hour_counts[h] = hour_counts.get(h, 0) + 1
        first_hour = min([8] + list(hour_counts))
        last_hour = max([19] + list(hour_counts))
        day_chart = [{
            'label': hour_label(h),
            'tooltip': f"{h % 12 or 12}:00 {'AM' if h < 12 else 'PM'}",
            'count': hour_counts.get(h, 0),
            'is_current': h == now_local.hour,
        } for h in range(first_hour, last_hour + 1)]

        week_chart = []
        for i in range(7):
            d = week_start + timedelta(days=i)
            week_chart.append({
                'label': d.strftime('%a'),
                'tooltip': d.strftime('%a %d %b'),
                'count': per_day.get(d, 0),
                'is_current': d == today,
            })

        _weekday, last_day = calendar.monthrange(today.year, today.month)
        month_chart = []
        for s, e in [(1, 7), (8, 14), (15, 21), (22, last_day)]:
            month_chart.append({
                'label': f"{s}-{e}",
                'tooltip': f"{s}-{e} {today.strftime('%b')}",
                'count': sum(per_day.get(date(today.year, today.month, x), 0) for x in range(s, e + 1)),
                'is_current': s <= today.day <= e,
            })

        year_chart = []
        for m in range(1, 13):
            year_chart.append({
                'label': calendar.month_abbr[m],
                'tooltip': f"{calendar.month_name[m]} {today.year}",
                'count': sum(c for d, c in per_day.items() if d.year == today.year and d.month == m),
                'is_current': m == today.month,
            })

        # Greeting & doctor profile
        hour = now_local.hour
        greeting = _("Good Morning") if hour < 12 else (_("Good Afternoon") if hour < 17 else _("Good Evening"))
        raw_name = selected_doctor.name or user.name or _('Doctor')
        short_name = raw_name.replace('Dr. ', '').replace('Dr ', '').strip()

        return {
            'has_doctor': True,
            'date_label': now_local.strftime('%A, %d %B %Y'),
            'refreshed_at': now_local.strftime('%I:%M %p').lstrip('0'),
            'doctor_info': {
                'id': selected_doctor.id or False,
                'name': short_name,
                'display_name': f"Dr. {short_name}",
                'greeting': f"{greeting}, Dr. {short_name}",
                'specialization': selected_doctor.specialization or _('Dental Surgeon'),
                'branch_name': company.name or '',
                'avatar_url': (f'/web/image?model=hr.employee.public&field=avatar_128&id={selected_doctor.id}' if selected_doctor
                               else f'/web/image?model=res.users&field=avatar_128&id={user.id}'),
            },
            'kpi_stats': {
                'appointments_today': len(live_today),
                'remaining_today': len(remaining_today),
                'waiting': len(waiting),
                'longest_wait_mins': max([int((now_utc - a.check_in_time).total_seconds() // 60) for a in waiting if a.check_in_time] + [0]),
                'completed_today': len(completed_today),
                'completion_pct': round(len(completed_today) * 100 / len(live_today)) if live_today else 0,
                'cancelled_today': len(cancelled_today),
                'new_patients_today': new_patients_today,
                'followups_due': followups_due,
                'patients_month': len(month_appts.mapped('patient_id')),
                'treatment_value_month': format_amount(self.env, month_value, company.currency_id),
            },
            'current_patient': current._dentist_dashboard_row(user_tz, now_utc) if current else False,
            'waiting_queue': [a._dentist_dashboard_row(user_tz, now_utc) for a in waiting],
            'today_schedule': [a._dentist_dashboard_row(user_tz, now_utc) for a in today_appts],
            'overview_charts': {
                'day': day_chart,
                'week': week_chart,
                'month': month_chart,
                'year': year_chart,
            },
        }
