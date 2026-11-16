# pyrefly: ignore[missing-import]
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
# pyrefly: ignore[missing-import]
from odoo.tools import html2plaintext

from .account_move import dental_billing_summary

# Case fields that edit today's examination inline (case field -> examination field)
VISIT_EXAM_FIELDS = {
    'exam_presenting_complaint': 'presenting_complaint',
    'exam_oral_hygiene': 'oral_hygiene',
    'exam_gum_condition': 'gum_condition',
    'exam_occlusion': 'occlusion',
    'exam_soft_tissue_findings': 'soft_tissue_findings',
    'exam_tooth_condition_summary': 'tooth_condition_summary',
    'exam_clinical_findings': 'clinical_findings',
    'exam_blood_pressure': 'blood_pressure',
    'exam_pulse_rate': 'pulse_rate',
    'exam_temperature': 'temperature',
}


class DentalCase(models.Model):
    _name = 'dental.case'
    _description = 'Dental Case'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'dental.company.mixin']

    name = fields.Char(string='Case Number', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    patient_id = fields.Many2one('res.partner', string='Patient', required=True, domain=[('is_dental_patient', '=', True)], tracking=True)
    doctor_id = fields.Many2one('hr.employee.public', string='Doctor', tracking=True)
    appointment_id = fields.Many2one('dental.appointment', string='Related Appointment', tracking=True, check_company=True)
    branch_id = fields.Many2one('res.company', string='Branch', related='appointment_id.branch_id', store=True)
    
    case_date = fields.Date(string='Case Date', default=fields.Date.context_today, required=True, tracking=True)
    
    chief_complaint = fields.Text(string='Chief Complaint')
    clinical_notes = fields.Text(string='Clinical Notes')
    
    medical_history_summary = fields.Text(string='Medical History Summary')
    dental_history_summary = fields.Text(string='Dental History Summary')
    # Snapshot copied from the patient when the case was opened (kept as part of the case record)
    allergies = fields.Text(string='Allergies (at case opening)')
    current_medications = fields.Text(string='Current Medications')

    # Live medical alert: always read from the patient record, never from the snapshot above
    patient_allergy_status = fields.Selection(related='patient_id.allergy_status', string='Allergy Status')
    patient_allergies = fields.Html(related='patient_id.allergies', string='Current Allergies')
    patient_allergy_verified_by = fields.Many2one(related='patient_id.allergy_verified_by', string='Allergies Verified By')
    patient_allergy_verified_date = fields.Datetime(related='patient_id.allergy_verified_date', string='Allergies Verified On')
    patient_clinical_alerts = fields.Html(related='patient_id.clinical_alerts', string='Clinical Alerts')
    patient_existing_conditions = fields.Html(related='patient_id.existing_conditions', string='Medical Conditions')
    patient_current_medications = fields.Html(related='patient_id.current_medications', string='Current Patient Medications')
    has_clinical_alert = fields.Boolean(string='Has Clinical Alert', compute='_compute_has_clinical_alert')
    # Patient card at the top of the case
    patient_image = fields.Image(related='patient_id.image_128', string='Patient Photo')
    patient_age = fields.Integer(related='patient_id.age', string='Patient Age')
    patient_gender = fields.Selection(related='patient_id.gender', string='Patient Gender')
    patient_allergy_verification = fields.Char(string='Allergy Verification', compute='_compute_patient_allergy_verification')

    @api.depends('patient_id.allergy_verified_by', 'patient_id.allergy_verified_date')
    @api.depends_context('tz')
    def _compute_patient_allergy_verification(self):
        for case in self:
            partner = case.patient_id
            if partner.allergy_verified_date:
                when = fields.Datetime.context_timestamp(case, partner.allergy_verified_date).strftime('%d %b %Y')
                case.patient_allergy_verification = _("Verified by %(user)s on %(date)s",
                                                      user=partner.allergy_verified_by.name or _('unknown'), date=when)
            else:
                case.patient_allergy_verification = _("Not verified")

    @api.depends('patient_id.clinical_alerts', 'patient_id.existing_conditions')
    def _compute_has_clinical_alert(self):
        nil = {'nil', 'none', 'n/a', 'no', 'na', '-'}
        for case in self:
            texts = (case._clean_text_from_html(case.patient_id.clinical_alerts),
                     case._clean_text_from_html(case.patient_id.existing_conditions))
            case.has_clinical_alert = any(t and t.lower() not in nil for t in texts)
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('under_treatment', 'Under Treatment'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Case Status', default='draft', tracking=True)
    
    examination_ids = fields.One2many('dental.clinical.examination', 'case_id', string='Examinations')
    tooth_finding_ids = fields.One2many('dental.tooth.finding', 'case_id', string='Tooth Findings')
    odontogram_chart = fields.Text(string='Odontogram Chart', default='{}')
    diagnosis_ids = fields.One2many('dental.patient.diagnosis', 'case_id', string='Diagnoses')
    # Clinical Chart list: the patient's open diagnoses from every visit (they stay until resolved),
    # plus the ones resolved in this case, in chart order
    patient_diagnosis_ids = fields.Many2many('dental.patient.diagnosis', string='Patient Diagnoses',
                                             compute='_compute_patient_diagnosis_ids')
    treatment_plan_ids = fields.One2many('dental.treatment.plan', 'case_id', string='Treatment Plans')
    treatment_session_ids = fields.One2many('dental.treatment.session', 'case_id', string='Treatment Sessions')
    treatment_line_ids = fields.One2many('dental.treatment.plan.line', 'case_id', string='Planned Treatments', readonly=True)
    follow_up_ids = fields.One2many('dental.follow.up', 'case_id', string='Follow-ups')
    completion_time = fields.Datetime(string='Completion Time', readonly=True)

    _appointment_uniq = models.Constraint(
        'unique(appointment_id)', 'A visit can open only one dental case; continue the existing case instead.')

    # Visits: the opening appointment plus every follow-up visit that continued this case
    visit_ids = fields.One2many('dental.appointment', 'case_id', string='Visits', readonly=True)
    visit_count = fields.Integer(string='Visits', compute='_compute_visit_info')
    current_examination_id = fields.Many2one('dental.clinical.examination', string='Current Consultation', compute='_compute_current_examination_id',
                                             help="Examination of today's visit. Earlier visits keep their own examination.")
    # Today's examination, edited inline on the case (written to the visit's own examination record)
    exam_presenting_complaint = fields.Text(compute='_compute_visit_exam_fields', readonly=False)
    exam_oral_hygiene = fields.Selection([('good', 'Good'), ('fair', 'Fair'), ('poor', 'Poor')], compute='_compute_visit_exam_fields', readonly=False)
    exam_gum_condition = fields.Char(compute='_compute_visit_exam_fields', readonly=False)
    exam_occlusion = fields.Char(compute='_compute_visit_exam_fields', readonly=False)
    exam_soft_tissue_findings = fields.Text(compute='_compute_visit_exam_fields', readonly=False)
    exam_tooth_condition_summary = fields.Text(compute='_compute_visit_exam_fields', readonly=False)
    exam_clinical_findings = fields.Text(compute='_compute_visit_exam_fields', readonly=False)
    exam_blood_pressure = fields.Char(compute='_compute_visit_exam_fields', readonly=False)
    exam_pulse_rate = fields.Integer(compute='_compute_visit_exam_fields', readonly=False)
    exam_temperature = fields.Float(compute='_compute_visit_exam_fields', readonly=False)
    current_visit_id = fields.Many2one('dental.appointment', string='Current Visit', compute='_compute_visit_info',
                                       help='Visit that new consultations, sessions and prescriptions are recorded against.')
    # Progress of today's structured examination, shown on the case's Examination tab
    current_exam_name = fields.Char(string='Examination', compute='_compute_current_exam_overview')
    current_exam_state = fields.Selection([('draft', 'In Progress'), ('done', 'Completed')], string='Examination Status',
                                          compute='_compute_current_exam_overview')
    current_exam_completed_by_id = fields.Many2one('res.users', string='Signed Off By', compute='_compute_current_exam_overview')
    current_exam_completed_date = fields.Datetime(string='Signed Off On', compute='_compute_current_exam_overview')
    current_exam_progress = fields.Float(string='Examination Progress', compute='_compute_current_exam_overview')
    current_exam_summary = fields.Text(string="Today's Examination", compute='_compute_current_exam_overview')
    current_exam_extraoral = fields.Boolean(string='Extraoral', compute='_compute_current_exam_overview')
    current_exam_intraoral = fields.Boolean(string='Intraoral', compute='_compute_current_exam_overview')
    current_exam_dental = fields.Boolean(string='Dental', compute='_compute_current_exam_overview')
    current_exam_periodontal = fields.Boolean(string='Periodontal', compute='_compute_current_exam_overview')
    current_exam_findings = fields.Boolean(string='Clinical Findings', compute='_compute_current_exam_overview')
    current_exam_diagnosis = fields.Boolean(string='Diagnosis', compute='_compute_current_exam_overview')
    current_exam_assessment = fields.Boolean(string='Assessment', compute='_compute_current_exam_overview')
    # Earlier examinations of the patient (every case), shown under today's on the Examination tab
    previous_examination_ids = fields.Many2many('dental.clinical.examination', string='Previous Examinations',
                                                compute='_compute_previous_examination_ids')

    # Patient history across all cases, limited to what the user's access rules allow
    previous_visit_count = fields.Integer(string='Previous Visits', compute='_compute_patient_history')
    last_visit_date = fields.Datetime(string='Last Visit', compute='_compute_patient_history')
    # Earlier completed visits of the patient (any case), shown as cards on the Overview tab
    previous_visit_ids = fields.Many2many('dental.appointment', string='Earlier Visits', compute='_compute_patient_history')
    history_case_ids = fields.Many2many('dental.case', string='Other Cases', compute='_compute_patient_history')
    history_examination_ids = fields.Many2many('dental.clinical.examination', string='Past Consultations', compute='_compute_patient_history')
    history_diagnosis_ids = fields.Many2many('dental.patient.diagnosis', string='All Diagnoses', compute='_compute_patient_history')
    history_plan_ids = fields.Many2many('dental.treatment.plan', string='All Treatment Plans', compute='_compute_patient_history')
    history_session_ids = fields.Many2many('dental.treatment.session', string='All Treatment Sessions', compute='_compute_patient_history')
    patient_document_ids = fields.Many2many('dental.patient.document', string='X-Rays & Records', compute='_compute_patient_history')
    # Read-only timeline from every branch, for patients who were treated at another branch before
    patient_history_line_ids = fields.One2many(related='patient_id.dental_history_ids', string='Treatment History (All Branches)',
                                               groups='dental_base.group_dental_dentist,dental_base.group_dental_manager')

    @api.depends('visit_ids.state', 'visit_ids.date_start', 'appointment_id.state')
    @api.depends_context('dental_current_visit_id')
    def _compute_visit_info(self):
        context_visit = self.env['dental.appointment'].browse(self.env.context.get('dental_current_visit_id'))
        for case in self:
            visits = case.visit_ids | case.appointment_id
            case.visit_count = len(visits)
            active = visits.filtered(lambda a: a.state in ('checked_in', 'in_consultation')).sorted('date_start', reverse=True)
            if context_visit and context_visit in visits:
                case.current_visit_id = context_visit
            elif active:
                case.current_visit_id = active[:1]
            else:
                case.current_visit_id = case.appointment_id

    @api.depends('examination_ids', 'examination_ids.examination_date', 'examination_ids.appointment_id', 'current_visit_id', 'appointment_id')
    def _compute_current_examination_id(self):
        for case in self:
            case.current_examination_id = case._find_visit_examination()

    @api.depends('current_examination_id')
    def _compute_visit_exam_fields(self):
        # Edited inline; writes go to the visit's examination in write() (no inverse needed)
        for case in self:
            exam = case.current_examination_id
            for case_field, exam_field in VISIT_EXAM_FIELDS.items():
                case[case_field] = exam[exam_field] if exam else False

    # case field -> examination field
    _CURRENT_EXAM_OVERVIEW = {
        'current_exam_name': 'name',
        'current_exam_state': 'state',
        'current_exam_completed_by_id': 'completed_by_id',
        'current_exam_completed_date': 'completed_date',
        'current_exam_progress': 'sections_progress',
        'current_exam_summary': 'examination_summary',
        'current_exam_extraoral': 'extraoral_recorded',
        'current_exam_intraoral': 'intraoral_recorded',
        'current_exam_dental': 'dental_recorded',
        'current_exam_periodontal': 'periodontal_recorded',
        'current_exam_findings': 'findings_recorded',
        'current_exam_diagnosis': 'diagnosis_recorded',
        'current_exam_assessment': 'assessment_recorded',
    }

    @api.depends('current_examination_id')
    def _compute_current_exam_overview(self):
        # Not stored: recomputed on every read, so it always reflects the examination as saved
        for case in self:
            exam = case.current_examination_id
            for case_field, exam_field in self._CURRENT_EXAM_OVERVIEW.items():
                case[case_field] = exam[exam_field] if exam else False

    @api.depends('patient_id', 'current_examination_id')
    def _compute_previous_examination_ids(self):
        Exam = self.env['dental.clinical.examination']
        for case in self:
            if not case.patient_id:
                case.previous_examination_ids = False
                continue
            case.previous_examination_ids = Exam.search([
                ('patient_id', '=', case.patient_id.id),
                ('id', '!=', case.current_examination_id.id),
            ], order='examination_date desc, id desc')

    def _continue_examination_from(self, source):
        """Carry an earlier examination's findings into today's visit and open it.

        The earlier examination is left untouched (it stays the record of its own visit).
        Today's examination is created if needed; one that already holds findings is never
        overwritten.
        """
        self.ensure_one()
        source.ensure_one()
        if source.patient_id != self.patient_id:
            raise UserError(_("Examination %s belongs to another patient.", source.name))
        if self.state in ('completed', 'cancelled'):
            raise UserError(_("Case %s is closed; reopen it to record a new examination.", self.name))
        Exam = self.env['dental.clinical.examination']
        Exam.check_access('create')
        current = self._find_visit_examination()
        if current == source:
            return self.action_open_examination()
        if current and (current.state == 'done' or current.sections_progress or current.tooth_finding_ids):
            raise UserError(_(
                "Today's examination %s already has findings recorded. Open it and update it instead "
                "of continuing an earlier examination.", current.name))
        vals = source._prepare_carry_forward_vals()
        vals['continued_from_id'] = source.id
        exam = current or self._get_visit_examination()
        exam.perio_chart_ids.unlink()
        exam.write(vals)
        exam.message_post(body=_(
            "Continued from examination %(name)s of %(date)s. Findings were carried forward: "
            "review each section and update what changed.",
            name=source.name, date=fields.Date.to_string(source.examination_date.date())))
        self.invalidate_recordset()
        return self.action_open_examination()

    def _find_visit_examination(self):
        """Examination of the current visit. A follow-up visit never reuses an earlier visit's
        examination, so recording today's findings cannot overwrite history. Cases without any
        visit fall back to their latest examination."""
        self.ensure_one()
        exams = self.examination_ids.sorted(lambda e: (e.examination_date or fields.Datetime.now(), e.id or 0), reverse=True)
        visit = self.current_visit_id or self.appointment_id
        if visit:
            return exams.filtered(lambda e: e.appointment_id == visit)[:1]
        return exams[:1]

    def _get_visit_examination(self):
        """Examination of the current visit, created on first use (one per visit)."""
        self.ensure_one()
        exam = self._find_visit_examination()
        if exam:
            return exam
        if self.state in ('completed', 'cancelled'):
            raise UserError(_("Case %s is closed; reopen it to record a new examination.", self.name))
        visit = self.current_visit_id or self.appointment_id
        exam = self.env['dental.clinical.examination'].create({
            'patient_id': self.patient_id.id,
            'case_id': self.id,
            'appointment_id': visit.id if visit else False,
            'doctor_id': (visit.doctor_id if visit and visit.doctor_id else self.doctor_id).id,
            'chief_complaint': (self._extract_chief_complaint_from_appointment(visit) if visit else False) or self.chief_complaint,
        })
        self.invalidate_recordset(['current_examination_id', 'examination_ids'])
        return exam

    @api.model
    def _pop_visit_exam_vals(self, vals):
        return {VISIT_EXAM_FIELDS[key]: vals.pop(key) for key in list(vals) if key in VISIT_EXAM_FIELDS}

    def _write_visit_exam_vals(self, exam_vals):
        if not exam_vals:
            return
        for case in self:
            if case.state in ('completed', 'cancelled'):
                raise UserError(_("Case %s is closed; reopen it to change today's examination.", case.name))
            case._get_visit_examination().write(exam_vals)
        self.invalidate_recordset(list(VISIT_EXAM_FIELDS))

    def _compute_patient_history(self):
        for case in self:
            patient = case.patient_id
            if not patient:
                case.update({
                    'previous_visit_count': 0, 'last_visit_date': False, 'previous_visit_ids': False,
                    'history_case_ids': False, 'history_examination_ids': False, 'history_diagnosis_ids': False,
                    'history_plan_ids': False, 'history_session_ids': False, 'patient_document_ids': False,
                })
                continue
            domain = [('patient_id', '=', patient.id)]
            past_visits = self.env['dental.appointment'].search(
                domain + [('state', '=', 'completed'), ('id', '!=', case.current_visit_id.id)], order='date_start desc')
            case.previous_visit_count = len(past_visits)
            case.last_visit_date = past_visits[:1].date_start
            case.previous_visit_ids = past_visits.filtered('case_id')
            case.history_case_ids = self.env['dental.case'].search(domain + [('id', '!=', case._origin.id)], order='case_date desc')
            case.history_examination_ids = self.env['dental.clinical.examination'].search(domain, order='examination_date desc')
            case.history_diagnosis_ids = self.env['dental.patient.diagnosis'].search(domain, order='date desc')
            case.history_plan_ids = self.env['dental.treatment.plan'].search(domain, order='plan_date desc')
            case.history_session_ids = self.env['dental.treatment.session'].search(domain, order='session_date desc')
            case.patient_document_ids = self.env['dental.patient.document'].search(domain)

    @api.depends('patient_id', 'diagnosis_ids', 'diagnosis_ids.status', 'diagnosis_ids.tooth_reference')
    def _compute_patient_diagnosis_ids(self):
        Diagnosis = self.env['dental.patient.diagnosis']
        for case in self:
            if not case.patient_id:
                case.patient_diagnosis_ids = False
                continue
            domain = [('patient_id', '=', case.patient_id.id), ('status', '!=', 'resolved')]
            if case._origin.id:
                domain = ['&', ('patient_id', '=', case.patient_id.id),
                          '|', ('status', '!=', 'resolved'), ('case_id', '=', case._origin.id)]
            diagnoses = Diagnosis.search(domain, order='date desc, id desc')
            # The same diagnosis left open on several visits shows once (its latest record)
            seen = set()
            latest = Diagnosis
            for diag in diagnoses:
                key = (diag.diagnosis_id.id, (diag.tooth_reference or '').replace(' ', ''), diag.status == 'resolved')
                if key not in seen:
                    seen.add(key)
                    latest |= diag
            case.patient_diagnosis_ids = latest.sorted(
                lambda d: (d.status == 'resolved', d._tooth_sort_key()))

    def action_add_diagnosis(self):
        """Quick form (dialog) to record a diagnosis on this visit, with or without a tooth."""
        self.ensure_one()
        if self.state in ('completed', 'cancelled'):
            raise UserError(_("Case %s is closed; reopen it to add a diagnosis.", self.name))
        self.env['dental.patient.diagnosis'].check_access('create')
        return {
            'name': _('Add Diagnosis'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.patient.diagnosis',
            'view_mode': 'form',
            'views': [(self.env.ref('dental_core.view_dental_patient_diagnosis_quick_form').id, 'form')],
            'target': 'new',
            'context': {
                'default_case_id': self.id,
                'default_patient_id': self.patient_id.id,
                'default_doctor_id': self.doctor_id.id,
            },
        }

    def action_open_patient_medical(self):
        """Open the patient file (full page, with breadcrumb back to the case) to record allergies."""
        self.ensure_one()
        return {
            'name': self.patient_id.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': self.patient_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_new_treatment_plan(self):
        """Start a treatment plan for this case on its own page instead of a popup."""
        self.ensure_one()
        if self.state in ('completed', 'cancelled'):
            raise UserError(_("Case %s is closed; reopen it to plan new treatment.", self.name))
        self.env['dental.treatment.plan'].check_access('create')
        visit = self.current_visit_id or self.appointment_id
        plan = self.env['dental.treatment.plan'].create({
            'patient_id': self.patient_id.id,
            'case_id': self.id,
            'doctor_id': self.doctor_id.id,
            'appointment_id': visit.id if visit else False,
        })
        return {
            'name': plan.name,
            'type': 'ir.actions.act_window',
            'res_model': 'dental.treatment.plan',
            'res_id': plan.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_patient_timeline(self):
        """Full-screen, filterable clinical timeline of this patient (all visits, all branches)."""
        self.ensure_one()
        self.env['dental.patient.history'].check_access('read')
        action = self.env['ir.actions.act_window']._for_xml_id('dental_core.action_dental_patient_timeline')
        action.update({
            'name': _('Clinical Timeline – %s', self.patient_id.display_name),
            'domain': [('patient_id', '=', self.patient_id.id)],
        })
        return action

    def _get_billable_visits(self):
        """Visits whose consultation fee belongs to this case: the opening visit and attended follow-ups."""
        self.ensure_one()
        attended = self.visit_ids.filtered(lambda a: a.state in ('checked_in', 'in_consultation', 'completed'))
        return self.appointment_id | attended

    def action_new_visit_consultation(self):
        """Record a consultation (examination) for the current visit of this case."""
        self.ensure_one()
        exam = self._get_visit_examination()
        return {
            'name': _('Visit Consultation'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.clinical.examination',
            'view_mode': 'form',
            'res_id': exam.id,
            'target': 'current',
        }

    def action_open_examination(self):
        """Open the structured clinical examination of the current visit (started on first use)."""
        self.ensure_one()
        exam = self._find_visit_examination()
        if not exam:
            self.env['dental.clinical.examination'].check_access('create')
            exam = self._get_visit_examination()
        visit = exam.appointment_id or self.current_visit_id
        return {
            'name': exam.name,
            'type': 'ir.actions.act_window',
            'res_model': 'dental.clinical.examination',
            'res_id': exam.id,
            'view_mode': 'form',
            'views': [(self.env.ref('dental_core.view_dental_clinical_examination_form').id, 'form')],
            'context': {'dental_current_visit_id': visit.id} if visit else {},
            'target': 'current',
        }

    def action_new_case_for_current_visit(self):
        """Move today's visit out of this continued case into a new case (unrelated new problem)."""
        self.ensure_one()
        visit = self.current_visit_id
        if not visit or visit == self.appointment_id:
            raise UserError(_("Today's visit opened this case; there is nothing to separate."))
        return visit.action_new_clinical_case()

    def action_schedule_follow_up(self):
        """Plan the next visit of this case; booking it later keeps the visit inside this case."""
        self.ensure_one()
        return {
            'name': _('Schedule Follow-up'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.follow.up',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_case_id': self.id,
                'default_patient_id': self.patient_id.id,
                'default_doctor_id': self.doctor_id.id,
                'default_appointment_id': self.current_visit_id.id,
                'default_follow_up_type': 'next_visit' if self.state == 'under_treatment' else 'review',
            },
        }

    # Billing (standard customer invoices; Pharmacy invoices for this case are included too)
    invoice_ids = fields.One2many('account.move', 'dental_case_id', string='Invoices', readonly=True)
    invoice_count = fields.Integer(string='Invoice Count', compute='_compute_billing')
    amount_due = fields.Monetary(string='Amount Due', compute='_compute_billing', currency_field='company_currency_id')
    company_currency_id = fields.Many2one(related='company_id.currency_id', string='Company Currency')
    billing_state = fields.Selection([
        ('nothing', 'Nothing to Bill'),
        ('to_invoice', 'To Invoice'),
        ('draft', 'Invoice in Draft'),
        ('due', 'Payment Due'),
        ('paid', 'Paid'),
    ], string='Billing Status', compute='_compute_billing')
    has_draft_invoice = fields.Boolean(compute='_compute_billing')

    @api.depends('appointment_id.company_id')
    def _compute_company_id(self):
        self._set_company_from('appointment_id')

    @api.depends('invoice_ids.state', 'invoice_ids.amount_residual', 'treatment_session_ids.billing_state')
    def _compute_billing(self):
        for case in self:
            # Clinical users may lack accounting rights; billing status is informational
            has_billable = bool(case.id and case.sudo()._get_billable_line_vals())
            (case.billing_state, case.invoice_count, case.amount_due,
             case.has_draft_invoice) = dental_billing_summary(case.sudo().invoice_ids, has_billable)

    def _get_consultation_fee_line_vals(self):
        """One consultation fee per attended visit of this case (each visit is billed once)."""
        self.ensure_one()
        fees = []
        for visit in self._get_billable_visits():
            fee = visit._get_consultation_fee_line_vals(doctor=visit.doctor_id or self.doctor_id)
            if fee:
                fees.append(fee)
        return fees

    def _get_billable_sessions(self):
        """Completed, unbilled sessions of this case or performed during one of its visits."""
        self.ensure_one()
        domain = [('state', '=', 'completed'), '|', ('case_id', '=', self.id),
                  ('appointment_id', 'in', self._get_billable_visits().ids)]
        sessions = self.env['dental.treatment.session'].search(domain, order='session_date asc, id asc')
        return sessions.filtered(lambda s: s.billing_state == 'to_invoice')

    def _get_billable_line_vals(self):
        self.ensure_one()
        vals_list = list(self._get_consultation_fee_line_vals())
        priced = self.env['dental.treatment.session']
        for session in self._get_billable_sessions():
            vals_list.append(session._prepare_invoice_line_vals(billed_in_batch=priced))
            priced |= session
        return vals_list

    def _create_patient_invoice(self):
        """Bill everything delivered and not yet billed for this case.

        One invoice per visit: while the case still has a draft invoice, new items are added to it
        instead of opening a second invoice.
        """
        self.ensure_one()
        # Serialize concurrent billing of the same case so it can never be invoiced twice
        self.env.cr.execute("SELECT id FROM dental_case WHERE id = %s FOR UPDATE", (self.id,))
        self.invalidate_recordset()
        line_vals = self._get_billable_line_vals()
        if not line_vals:
            return self.env['account.move']
        invoice, extended = self.env['account.move']._dental_create_or_extend_invoice(
            self.patient_id, self.company_id, line_vals, case=self)
        if extended:
            msg = _("%(count)s item(s) added to draft invoice, new total %(amount)s.",
                    count=len(line_vals), amount=invoice.amount_total)
        else:
            msg = _("Draft invoice prepared with %(count)s line(s), total %(amount)s.",
                    count=len(line_vals), amount=invoice.amount_total)
        self.message_post(body=msg)
        return invoice

    def action_create_invoice(self):
        self.ensure_one()
        appt_model = self.env['dental.appointment']
        appt_model._check_billing_rights()
        # Doctors only bill cases their access rules let them see
        self.check_access('read')
        invoice = self.sudo()._create_patient_invoice()
        if not invoice:
            raise UserError(_("Nothing to invoice: the consultation fee is already billed and no treatment has been marked done since."))
        if self.env.user.has_group('account.group_account_invoice'):
            return self._action_open_invoices(invoice.with_env(self.env))
        return appt_model._billing_result_action(invoice)

    def action_view_invoices(self):
        self.ensure_one()
        return self._action_open_invoices(self.invoice_ids.filtered(lambda m: m.move_type == 'out_invoice'))

    def _action_open_invoices(self, invoices):
        action = {
            'name': _('Patient Invoices'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'context': {'default_move_type': 'out_invoice', 'default_partner_id': self.patient_id.id, 'default_dental_case_id': self.id},
        }
        if len(invoices) == 1:
            action.update({'view_mode': 'form', 'res_id': invoices.id})
        else:
            action.update({'view_mode': 'list,form', 'domain': [('id', 'in', invoices.ids)]})
        return action

    def _has_pending_treatment(self):
        """True while the case still has treatment work to deliver in later visits."""
        self.ensure_one()
        open_plans = self.treatment_plan_ids.filtered(lambda p: p.state not in ('completed', 'cancelled'))
        open_sessions = self.treatment_session_ids.filtered(lambda s: s.state in ('planned', 'in_progress'))
        return bool(open_plans or open_sessions)

    def action_complete_consultation(self):
        messages = []
        for record in self:
            if not record.chief_complaint:
                raise ValidationError(_("Chief Complaint is required to complete the consultation."))

            record.completion_time = fields.Datetime.now()
            # Found before the visit is closed: afterwards the case no longer points at today's visit
            exam = record._find_visit_examination()

            # Close today's visit (a follow-up visit for continued cases); walk-ins still in 'confirmed' are checked in on the way
            appt = record.current_visit_id
            if appt and appt.state in ('confirmed', 'checked_in', 'in_consultation'):
                if appt.state != 'in_consultation':
                    appt.action_start_consultation()
                appt.action_complete()

            # Today's examination is signed off with the consultation
            if exam and exam.state != 'done':
                exam._mark_done()

            # The case stays active while treatment remains; otherwise it is clinically closed
            if record._has_pending_treatment():
                record.state = 'under_treatment'
                msg = _("Consultation completed. Case remains Under Treatment until the planned treatment is finished.")
            else:
                record.state = 'completed'
                msg = _("Consultation completed and case closed.")
            record.message_post(body=msg)

            # Prepare today's bill for the front desk; doctors need no invoicing rights for this
            if record.company_id.dental_auto_invoice:
                try:
                    with self.env.cr.savepoint():
                        invoice = record.sudo()._create_patient_invoice()
                    if invoice:
                        msg = _("%(msg)s Draft invoice ready for billing (%(amount)s).", msg=msg, amount=invoice.amount_total)
                except UserError as err:
                    record.message_post(body=_("Automatic invoice skipped: %s", err.args[0] if err.args else err))
            messages.append(msg)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': messages[0] if len(messages) == 1 else _("Consultations completed."),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_reopen_case(self):
        self.filtered(lambda c: c.state in ('completed', 'cancelled')).write({'state': 'open'})

    @api.model
    def _clean_text_from_html(self, content):
        if not content:
            return ''
        text = html2plaintext(str(content)).strip()
        return text if text else ''

    @api.model
    def _extract_chief_complaint_from_appointment(self, appointment):
        if not appointment:
            return ''
        parts = []
        if appointment.reason:
            parts.append(appointment.reason.strip())
        if appointment.notes:
            clean_notes = self._clean_text_from_html(appointment.notes)
            if clean_notes and clean_notes not in parts and clean_notes not in (appointment.reason or ''):
                parts.append(f"Notes: {clean_notes}")
        return "\n".join(parts)

    @api.model
    def _extract_medical_history_from_patient(self, patient):
        if not patient:
            return ''
        parts = []
        ignore_values = {'nil', 'none', 'n/a', 'no', 'na', '-', ''}
        if hasattr(patient, 'existing_conditions') and patient.existing_conditions:
            cond = self._clean_text_from_html(patient.existing_conditions)
            if cond and cond.lower() not in ignore_values:
                parts.append(cond)
        if hasattr(patient, 'medical_history') and patient.medical_history:
            med = self._clean_text_from_html(patient.medical_history)
            if med and med.lower() not in ignore_values and med not in parts:
                parts.append(med)
        if hasattr(patient, 'previous_surgeries') and patient.previous_surgeries:
            surg = self._clean_text_from_html(patient.previous_surgeries)
            if surg and surg.lower() not in ignore_values and surg not in parts:
                parts.append(f"Previous Surgeries: {surg}")
        return "\n".join(parts)

    @api.model
    def _extract_allergies_from_patient(self, patient):
        if not patient or not hasattr(patient, 'allergies') or not patient.allergies:
            return ''
        return self._clean_text_from_html(patient.allergies)

    @api.model
    def _extract_medications_from_patient(self, patient):
        if not patient or not hasattr(patient, 'current_medications') or not patient.current_medications:
            return ''
        return self._clean_text_from_html(patient.current_medications)

    @api.model
    def _extract_dental_history_from_patient(self, patient):
        if not patient:
            return ''
        parts = []
        ignore_values = {'nil', 'none', 'n/a', 'no', 'na', '-', ''}
        if hasattr(patient, 'dental_history') and patient.dental_history:
            dh = self._clean_text_from_html(patient.dental_history)
            if dh and dh.lower() not in ignore_values:
                parts.append(dh)
        if hasattr(patient, 'previous_dental_treatments') and patient.previous_dental_treatments:
            pdt = self._clean_text_from_html(patient.previous_dental_treatments)
            if pdt and pdt.lower() not in ignore_values and pdt not in parts:
                parts.append(f"Previous Treatments: {pdt}")
        if hasattr(patient, 'last_dental_visit') and patient.last_dental_visit:
            parts.append(f"Last Visit: {patient.last_dental_visit}")
        if hasattr(patient, 'clinical_alerts') and patient.clinical_alerts:
            alerts = self._clean_text_from_html(patient.clinical_alerts)
            if alerts and alerts.lower() not in ignore_values and alerts not in parts:
                parts.append(f"Alert: {alerts}")
        return "\n".join(parts)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('dental.case') or _('New')

            # Pre-fetch appointment and patient records for auto-populating
            appt = self.env['dental.appointment'].browse(vals.get('appointment_id')) if vals.get('appointment_id') else False

            # A visit that already continues a case must not silently get a second one
            if appt and not self.env.context.get('dental_new_case_for_visit'):
                existing = appt.sudo().case_id
                if existing:
                    raise ValidationError(_(
                        "Visit %(visit)s already belongs to case %(case)s. Continue that case, or use "
                        "'Start New Case' on the appointment for an unrelated problem.",
                        visit=appt.sudo().name, case=existing.name))
            patient = self.env['res.partner'].browse(vals.get('patient_id')) if vals.get('patient_id') else (appt.patient_id if appt else False)

            # Auto-populate Chief Complaint from appointment if empty
            if not vals.get('chief_complaint') and appt:
                comp = self._extract_chief_complaint_from_appointment(appt)
                if comp:
                    vals['chief_complaint'] = comp

            # Auto-populate Medical & Dental History from patient if empty
            if patient:
                if not vals.get('medical_history_summary'):
                    med = self._extract_medical_history_from_patient(patient)
                    if med:
                        vals['medical_history_summary'] = med
                if not vals.get('allergies'):
                    allergies = self._extract_allergies_from_patient(patient)
                    if allergies:
                        vals['allergies'] = allergies
                if not vals.get('current_medications'):
                    meds = self._extract_medications_from_patient(patient)
                    if meds:
                        vals['current_medications'] = meds
                if not vals.get('dental_history_summary'):
                    dh = self._extract_dental_history_from_patient(patient)
                    if dh:
                        vals['dental_history_summary'] = dh

        vals_list = [dict(vals) for vals in vals_list]
        exam_vals_list = [self._pop_visit_exam_vals(vals) for vals in vals_list]
        cases = super().create(vals_list)
        for case, exam_vals in zip(cases, exam_vals_list):
            case._write_visit_exam_vals(exam_vals)
        return cases

    def write(self, vals):
        # Today's examination is a separate record per visit: route the inline fields to it
        # instead of through the related fields, which would silently drop them when no
        # examination exists yet for this visit.
        exam_vals = {}
        if any(k in VISIT_EXAM_FIELDS for k in vals):
            vals = dict(vals)
            exam_vals = self._pop_visit_exam_vals(vals)
        res = super().write(vals) if vals else True
        self._write_visit_exam_vals(exam_vals)
        return res

    @api.onchange('appointment_id')
    def _onchange_appointment_id(self):
        if self.appointment_id:
            if not self.patient_id and self.appointment_id.patient_id:
                self.patient_id = self.appointment_id.patient_id
            if not self.doctor_id and self.appointment_id.doctor_id:
                self.doctor_id = self.appointment_id.doctor_id
            if not self.chief_complaint:
                self.chief_complaint = self._extract_chief_complaint_from_appointment(self.appointment_id)

    @api.onchange('patient_id')
    def _onchange_patient_id(self):
        if self.patient_id:
            if not self.medical_history_summary:
                self.medical_history_summary = self._extract_medical_history_from_patient(self.patient_id)
            if not self.allergies:
                self.allergies = self._extract_allergies_from_patient(self.patient_id)
            if not self.current_medications:
                self.current_medications = self._extract_medications_from_patient(self.patient_id)
            if not self.dental_history_summary:
                self.dental_history_summary = self._extract_dental_history_from_patient(self.patient_id)

    def get_odontogram_data(self, patient_id=None):
        case = self and self[0] or None
        target_patient_id = patient_id or (case and case.patient_id.id)
        if not target_patient_id:
            return {
                'case_id': case.id if case else False,
                'patient_id': False,
                'patient_name': '',
                'doctor_id': case.doctor_id.id if case and case.doctor_id else False,
                'doctor_name': case.doctor_id.name if case and case.doctor_id else '',
                'teeth': {},
                'stats': {'sound': 32, 'caries': 0, 'restoration': 0, 'missing': 0, 'crown': 0, 'root_canal': 0, 'implant': 0, 'other': 0, 'total_teeth': 32},
                'can_edit': self.env.user.has_group('dental_base.group_dental_dentist') or self.env.user.has_group('dental_base.group_dental_manager') or self.env.user.has_group('dental_base.group_dental_admin'),
                'is_dentist': self.env.user.has_group('dental_base.group_dental_dentist') or self.env.user.has_group('dental_base.group_dental_manager') or self.env.user.has_group('dental_base.group_dental_admin')
            }

        patient = self.env['res.partner'].browse(target_patient_id)
        
        # Calculate patient age
        patient_age = patient.age if hasattr(patient, 'age') else 0
        if not patient_age and hasattr(patient, 'date_of_birth') and patient.date_of_birth:
            from datetime import date
            from dateutil.relativedelta import relativedelta
            patient_age = relativedelta(date.today(), patient.date_of_birth).years

        # Suggested dentition based on age:
        # 0-5: primary
        # 6-12: mixed
        # 13+: permanent
        if patient_age <= 5:
            suggested_dentition = 'primary'
        elif 6 <= patient_age <= 12:
            suggested_dentition = 'mixed'
        else:
            suggested_dentition = 'permanent'

        findings = self.env['dental.tooth.finding'].search([
            ('patient_id', '=', target_patient_id),
            ('active', '=', True)
        ], order='finding_date desc, id desc')

        from .dental_tooth_finding import PERIO_SITES, TOOTH_NAMES
        teeth = {}
        # Prepopulate 32 adult permanent teeth
        for quad in [1, 2, 3, 4]:
            for pos in range(1, 9):
                t_num = f"{quad}{pos}"
                teeth[t_num] = {
                    'tooth_number': t_num,
                    'is_primary': False,
                    'condition': 'sound',
                    'surfaces': '',
                    'severity': '',
                    'treatment_indicated': '',
                    'notes': '',
                    'latest_date': '',
                    'findings_count': 0,
                    'history': [],
                    'diagnoses': [],
                    'proposed_treatments': [],
                    'completed_treatments': [],
                    'sessions': []
                }
        # Prepopulate 20 primary deciduous teeth
        for quad in [5, 6, 7, 8]:
            for pos in range(1, 6):
                t_num = f"{quad}{pos}"
                teeth[t_num] = {
                    'tooth_number': t_num,
                    'is_primary': True,
                    'condition': 'sound',
                    'surfaces': '',
                    'severity': '',
                    'treatment_indicated': '',
                    'notes': '',
                    'latest_date': '',
                    'findings_count': 0,
                    'history': [],
                    'diagnoses': [],
                    'proposed_treatments': [],
                    'completed_treatments': [],
                    'sessions': []
                }

        for f in findings:
            t_num = str(f.tooth_number).strip()
            if t_num not in teeth:
                teeth[t_num] = {
                    'tooth_number': t_num,
                    'condition': 'sound',
                    'surfaces': '',
                    'severity': '',
                    'treatment_indicated': '',
                    'notes': '',
                    'latest_date': '',
                    'findings_count': 0,
                    'history': [],
                    'diagnoses': [],
                    'proposed_treatments': [],
                    'completed_treatments': [],
                    'sessions': []
                }
            entry = teeth[t_num]
            entry['findings_count'] += 1
            if len(entry['history']) == 0:
                entry['condition'] = f.condition
                entry['surfaces'] = f.surfaces or ''
                entry['severity'] = f.severity or ''
                entry['treatment_indicated'] = f.treatment_indicated or ''
                entry['notes'] = f.notes or ''
                entry['latest_date'] = f.finding_date.strftime('%d %b %Y %H:%M') if f.finding_date else ''
                entry['latest_case_name'] = f.case_id.name if f.case_id else ''
                entry['restoration_type'] = f.restoration_type or ''
                entry['restoration_material'] = f.restoration_material or ''
                entry['restoration_quality'] = f.restoration_quality or ''
                entry['restoration_detail'] = f.restoration_detail or ''
                entry['surface_details'] = f.surface_details or ''
                entry['clinical_action'] = f.clinical_action or ''

            # Perio charting and pulp tests are often recorded on their own visit: keep the
            # most recent reading even when a later finding did not repeat it.
            if 'perio' not in entry and f.perio_max_depth:
                entry['perio'] = {site: f[site] for site in PERIO_SITES}
            if 'endo_tests' not in entry and f.endo_tests:
                entry['endo_tests'] = f.endo_tests

            entry['history'].append({
                'id': f.id,
                'name': f.name,
                'date': f.finding_date.strftime('%d %b %Y %H:%M') if f.finding_date else '',
                'condition': f.condition,
                'condition_label': dict(f._fields['condition'].selection).get(f.condition, f.condition),
                'surfaces': f.surfaces or '',
                'severity': f.severity or '',
                'severity_label': dict(f._fields['severity'].selection).get(f.severity, f.severity) if f.severity else '',
                'diagnosis_id': f.diagnosis_id.id if hasattr(f, 'diagnosis_id') and f.diagnosis_id else False,
                'diagnosis_name': f.diagnosis_id.name if hasattr(f, 'diagnosis_id') and f.diagnosis_id else '',
                'treatment_indicated': f.treatment_indicated or '',
                'notes': f.notes or '',
                'restoration_summary': ', '.join(
                    dict(f._fields[fname].selection)[f[fname]]
                    for fname in ('restoration_type', 'restoration_material', 'restoration_quality', 'restoration_detail')
                    if f[fname]
                ),
                'clinical_action': f.clinical_action or '',
                'endo_summary': f.endo_summary or '',
                'perio_max_depth': f.perio_max_depth,
                'case_id': f.case_id.id if f.case_id else False,
                'case_name': f.case_id.name if f.case_id else _('Historical Visit'),
                'doctor_name': f.doctor_id.name if f.doctor_id else '',
                'is_current_case': bool(case and f.case_id.id == case.id)
            })

            if hasattr(f, 'diagnosis_id') and f.diagnosis_id:
                entry['diagnoses'].append({
                    'key': f'finding_{f.id}',
                    'id': f.id,
                    'diagnosis_id': f.diagnosis_id.id,
                    'diagnosis_name': f.diagnosis_id.name,
                    'diagnosis_code': f.diagnosis_id.code or '',
                    'date': f.finding_date.strftime('%d %b %Y') if f.finding_date else '',
                    'status': 'confirmed',
                    'status_label': _('Confirmed Finding'),
                    'doctor_name': f.doctor_id.name if f.doctor_id else '',
                    'notes': f.notes or '',
                    'case_name': f.case_id.name if f.case_id else '',
                })

        for t_num, entry in teeth.items():
            info = TOOTH_NAMES.get(t_num)
            if info:
                entry['tooth_name'] = info[0]
                entry['universal_number'] = info[1]
                entry['palmer_notation'] = info[2]
            else:
                entry['tooth_name'] = f"Tooth {t_num}"
                entry['universal_number'] = t_num
                entry['palmer_notation'] = t_num

        patient_diags = self.env['dental.patient.diagnosis'].search([
            ('patient_id', '=', target_patient_id)
        ], order='date desc, id desc')
        for pd in patient_diags:
            ref = str(getattr(pd, 'tooth_reference', '') or '').strip()
            pd_item = {
                'key': f'diagnosis_{pd.id}',
                'id': pd.id,
                'diagnosis_id': pd.diagnosis_id.id,
                'diagnosis_name': pd.diagnosis_id.name,
                'diagnosis_code': pd.diagnosis_id.code or '',
                'date': pd.date.strftime('%d %b %Y') if pd.date else '',
                'status': pd.status,
                'status_label': dict(pd._fields['status'].selection).get(pd.status, pd.status),
                'doctor_name': pd.doctor_id.name if pd.doctor_id else '',
                'notes': pd.notes or '',
                'case_id': pd.case_id.id if pd.case_id else False,
                'case_name': pd.case_id.name if pd.case_id else '',
            }
            if ref:
                parts = [x.strip() for x in ref.replace(';', ',').split(',') if x.strip()]
                for t_num in teeth:
                    if t_num in parts:
                        teeth[t_num]['diagnoses'].append(pd_item)

        plan_lines = self.env['dental.treatment.plan.line'].search([
            ('plan_id.patient_id', '=', target_patient_id)
        ])
        for line in plan_lines:
            ref = str(line.tooth_reference or '').strip()
            if ref:
                parts = [x.strip() for x in ref.replace(';', ',').split(',') if x.strip()]
                for t_num in teeth:
                    if t_num in parts or ref == t_num:
                        item = {
                            'key': f'plan_line_{line.id}',
                            'id': line.id,
                            'plan_id': line.plan_id.id,
                            'plan_name': line.plan_id.name,
                            'treatment_name': line.treatment_id.name if line.treatment_id else _('Dental Procedure'),
                            'description': line.description or '',
                            'state': line.state,
                            'state_label': dict(line._fields['state'].selection).get(line.state, line.state),
                            'estimated_amount': line.estimated_amount,
                            'is_completed': line.state == 'completed',
                        }
                        if line.state == 'completed':
                            teeth[t_num]['completed_treatments'].append(item)
                        else:
                            teeth[t_num]['proposed_treatments'].append(item)

        sessions = self.env['dental.treatment.session'].search([
            ('patient_id', '=', target_patient_id)
        ], order='session_date desc, id desc')
        for sess in sessions:
            ref = str(sess.tooth_reference or '').strip()
            if ref:
                parts = [x.strip() for x in ref.replace(';', ',').split(',') if x.strip()]
                for t_num in teeth:
                    if t_num in parts or ref == t_num:
                        t_name = sess.plan_line_id.treatment_id.name if sess.plan_line_id and sess.plan_line_id.treatment_id else sess.name
                        item = {
                            'key': f'session_{sess.id}',
                            'id': sess.id,
                            'name': sess.name,
                            'treatment_name': t_name,
                            'date': sess.session_date.strftime('%d %b %Y') if sess.session_date else '',
                            'state': sess.state,
                            'state_label': dict(sess._fields['state'].selection).get(sess.state, sess.state),
                            'doctor_name': sess.doctor_id.name if sess.doctor_id else '',
                            'procedure_notes': sess.procedure_notes or '',
                            'is_completed': sess.state == 'completed',
                        }
                        teeth[t_num]['sessions'].append(item)
                        if sess.state == 'completed':
                            teeth[t_num]['completed_treatments'].append(item)

        stats = {
            'sound': 0,
            'caries': 0,
            'restoration': 0,
            'missing': 0,
            'dummy_permanent': 0,
            'dummy_temporary': 0,
            'crown': 0,
            'root_canal': 0,
            'implant': 0,
            'other': 0,
            'total_teeth': 32
        }
        for q in [1, 2, 3, 4]:
            for p in range(1, 9):
                tn = f"{q}{p}"
                cond = teeth.get(tn, {}).get('condition', 'sound')
                if cond in stats:
                    stats[cond] += 1
                elif cond == 'sound':
                    stats['sound'] += 1
                else:
                    stats['other'] += 1

        is_dentist = (
            self.env.user.has_group('dental_base.group_dental_dentist') or 
            self.env.user.has_group('dental_base.group_dental_manager') or
            self.env.user.has_group('dental_base.group_dental_admin')
        )

        diagnosis_masters = self.env['dental.diagnosis'].search_read(
            [('active', '=', True)],
            ['id', 'name', 'code', 'category'],
            order='code asc, name asc'
        )

        # Check if saved dentition exists in case.odontogram_chart
        saved_dentition = False
        if case and case.odontogram_chart:
            try:
                import json
                chart_data = json.loads(case.odontogram_chart)
                if isinstance(chart_data, dict) and chart_data.get('dentition'):
                    saved_dentition = chart_data.get('dentition')
            except Exception:
                pass

        # Identify which teeth have recorded findings, non-sound conditions, or treatments
        permanent_exclusive_teeth = {
            '13', '14', '15', '17', '18',
            '23', '24', '25', '27', '28',
            '33', '34', '35', '37', '38',
            '43', '44', '45', '47', '48'
        }
        mixed_permanent_teeth = {'11', '12', '16', '21', '22', '26', '31', '32', '36', '41', '42', '46'}
        all_permanent_teeth = permanent_exclusive_teeth | mixed_permanent_teeth

        def tooth_has_records(t_data):
            if not t_data:
                return False
            if t_data.get('condition', 'sound') != 'sound':
                return True
            if t_data.get('findings_count', 0) > 0 or len(t_data.get('history', [])) > 0:
                return True
            if len(t_data.get('diagnoses', [])) > 0:
                return True
            if len(t_data.get('completed_treatments', [])) > 0 or len(t_data.get('proposed_treatments', [])) > 0:
                return True
            if len(t_data.get('sessions', [])) > 0:
                return True
            return False

        has_permanent_treatments = False
        has_permanent_exclusive_treatments = False
        for tn in all_permanent_teeth:
            if tooth_has_records(teeth.get(tn)):
                has_permanent_treatments = True
                if tn in permanent_exclusive_teeth:
                    has_permanent_exclusive_treatments = True

        if has_permanent_exclusive_treatments or (has_permanent_treatments and saved_dentition == 'permanent'):
            minimum_dentition = 'permanent'
        elif has_permanent_treatments:
            minimum_dentition = 'mixed'
        else:
            minimum_dentition = 'primary'

        return {
            'case_id': case.id if case else False,
            'case_name': case.name if case else '',
            'case_state': case.state if case else '',
            'patient_id': patient.id,
            'patient_name': patient.name,
            'patient_ref': patient.ref or (getattr(patient, 'patient_id_number', False) or ''),
            'patient_dob': patient.date_of_birth.strftime('%d %b %Y') if hasattr(patient, 'date_of_birth') and patient.date_of_birth else '',
            'patient_age': patient_age,
            'suggested_dentition': suggested_dentition,
            'saved_dentition': saved_dentition,
            'minimum_dentition': minimum_dentition,
            'has_permanent_treatments': has_permanent_treatments,
            'doctor_id': case.doctor_id.id if case and case.doctor_id else False,
            'doctor_name': case.doctor_id.name if case and case.doctor_id else '',
            'teeth': teeth,
            'stats': stats,
            'diagnosis_masters': diagnosis_masters,
            'can_edit': is_dentist and (case.state not in ['completed', 'cancelled'] if case else True),
            'is_dentist': is_dentist,
        }

    @api.model
    def _prepare_tooth_finding_details(self, tooth_data):
        """Validate the optional restoration / endodontic / periodontal details sent by the
        odontogram widget and return them as dental.tooth.finding values."""
        from .dental_tooth_finding import ENDO_RESULTS, ENDO_TESTS, PERIO_SITES, SURFACE_DETAILS

        Finding = self.env['dental.tooth.finding']
        vals = {}
        for fname in ('restoration_type', 'restoration_material', 'restoration_quality',
                      'restoration_detail', 'clinical_action'):
            value = tooth_data.get(fname) or False
            allowed = dict(Finding._fields[fname].selection)
            vals[fname] = value if value in allowed else False

        details = tooth_data.get('surface_details') or []
        if isinstance(details, str):
            details = details.split(',')
        vals['surface_details'] = ','.join(d for d in details if d in SURFACE_DETAILS)

        endo = tooth_data.get('endo_tests') or {}
        endo = {k: v for k, v in endo.items() if k in ENDO_TESTS and v in ENDO_RESULTS} if isinstance(endo, dict) else {}
        vals['endo_tests'] = endo or False

        perio = tooth_data.get('perio') or {}
        for site in PERIO_SITES:
            try:
                depth = int((perio or {}).get(site) or 0)
            except (TypeError, ValueError):
                depth = 0
            vals[site] = min(max(depth, 0), 20)

        if vals['clinical_action'] == 'treat':
            vals['state'] = 'planned'
        return vals

    def save_tooth_finding(self, tooth_data):
        self.ensure_one()
        is_dentist = (
            self.env.user.has_group('dental_base.group_dental_dentist') or 
            self.env.user.has_group('dental_base.group_dental_manager') or
            self.env.user.has_group('dental_base.group_dental_admin')
        )
        if not is_dentist:
            raise UserError(_("Access Denied: Only authorized dentists and clinic managers can record tooth findings."))

        if self.state in ['completed', 'cancelled']:
            raise UserError(_("Tooth findings cannot be added to a completed or cancelled dental case."))

        tooth_number = str(tooth_data.get('tooth_number', '')).strip()
        if not tooth_number:
            raise ValidationError(_("Tooth number is required."))

        condition = tooth_data.get('condition', 'sound')
        surfaces = str(tooth_data.get('surfaces', '')).strip().upper()
        severity = tooth_data.get('severity', 'moderate')
        treatment_indicated = tooth_data.get('treatment_indicated', '')
        notes = tooth_data.get('notes', '')

        diagnosis_id = tooth_data.get('diagnosis_id')
        if diagnosis_id:
            try:
                diagnosis_id = int(diagnosis_id)
            except (ValueError, TypeError):
                diagnosis_id = False
        else:
            diagnosis_id = False

        doctor = self.doctor_id
        if not doctor and hasattr(self.env.user, 'employee_ids') and self.env.user.employee_ids:
            doctor = self.env.user.employee_ids[0]

        exam = self._get_visit_examination()
        finding_vals = {
            'patient_id': self.patient_id.id,
            'case_id': self.id,
            'examination_id': exam.id,
            'doctor_id': doctor.id if doctor else False,
            'tooth_number': tooth_number,
            'condition': condition,
            'surfaces': surfaces,
            'severity': severity,
            'treatment_indicated': treatment_indicated,
            'notes': notes,
            'finding_date': fields.Datetime.now(),
            'state': 'active',
        }
        if diagnosis_id:
            finding_vals['diagnosis_id'] = diagnosis_id
        finding_vals.update(self._prepare_tooth_finding_details(tooth_data))

        finding = self.env['dental.tooth.finding'].create(finding_vals)

        if diagnosis_id:
            # A diagnosis stays open across visits: the same diagnosis on the same tooth is not
            # recorded again while an earlier one (any visit) is still open
            existing_diag = self.env['dental.patient.diagnosis'].search([
                ('patient_id', '=', self.patient_id.id),
                ('diagnosis_id', '=', diagnosis_id),
                ('tooth_reference', '=', tooth_number),
                '|', ('case_id', '=', self.id), ('status', '!=', 'resolved'),
            ], limit=1)
            if not existing_diag:
                self.env['dental.patient.diagnosis'].create({
                    'patient_id': self.patient_id.id,
                    'case_id': self.id,
                    'examination_id': exam.id,
                    'doctor_id': doctor.id if doctor else False,
                    'diagnosis_id': diagnosis_id,
                    'tooth_reference': tooth_number,
                    'notes': notes or False,
                    'status': 'confirmed',
                })

        return {
            'success': True,
            'finding_id': finding.id,
            'finding_name': finding.name,
            'odontogram_data': self.get_odontogram_data()
        }

    def clear_tooth_finding(self, tooth_number):
        self.ensure_one()
        is_dentist = (
            self.env.user.has_group('dental_base.group_dental_dentist') or 
            self.env.user.has_group('dental_base.group_dental_manager') or
            self.env.user.has_group('dental_base.group_dental_admin')
        )
        if not is_dentist:
            raise UserError(_("Access Denied: Only authorized dentists and clinic managers can modify tooth findings."))

        if self.state in ['completed', 'cancelled']:
            raise UserError(_("Tooth findings cannot be modified in a completed or cancelled dental case."))

        t_num = str(tooth_number or '').strip()
        if not t_num:
            raise ValidationError(_("Tooth number is required."))

        # Create a new sound finding record to document the resolution/clear status
        doctor = self.doctor_id
        if not doctor and hasattr(self.env.user, 'employee_ids') and self.env.user.employee_ids:
            doctor = self.env.user.employee_ids[0]

        finding = self.env['dental.tooth.finding'].create({
            'patient_id': self.patient_id.id,
            'case_id': self.id,
            'examination_id': self._get_visit_examination().id,
            'doctor_id': doctor.id if doctor else False,
            'tooth_number': t_num,
            'condition': 'sound',
            'surfaces': '',
            'severity': 'mild',
            'notes': _('Cleared / Marked Sound during consultation'),
            'finding_date': fields.Datetime.now(),
            'state': 'active',
        })
        # A tooth charted healthy again: its open diagnoses are resolved (kept as history)
        self.env['dental.patient.diagnosis'].search([
            ('patient_id', '=', self.patient_id.id),
            ('tooth_reference', '=', t_num),
            ('status', '!=', 'resolved'),
        ]).action_mark_resolved()

        return {
            'success': True,
            'finding_id': finding.id,
            'odontogram_data': self.get_odontogram_data()
        }

