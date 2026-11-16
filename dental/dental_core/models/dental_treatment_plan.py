from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

TREATMENT_PHASES = [
    ('1', 'Phase 1 - Urgent / Pain Relief'),
    ('2', 'Phase 2 - Disease Control'),
    ('3', 'Phase 3 - Restorative / Definitive'),
    ('4', 'Phase 4 - Maintenance'),
]
TREATMENT_PRIORITIES = [
    ('0', 'Routine'),
    ('1', 'Soon'),
    ('2', 'Urgent'),
]

class DentalTreatmentStage(models.Model):
    _name = 'dental.treatment.stage'
    _description = 'Treatment Stage'
    _order = 'sequence, id'

    name = fields.Char(string='Stage Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    treatment_id = fields.Many2one(
        'product.template',
        string='Treatment',
        domain=[('is_dental_treatment', '=', True)],
        help='If set, this stage is only applicable to this specific dental treatment. Otherwise, it is available across all treatments.',
    )
    stage_type = fields.Selection([
        ('planned', 'Planned / Initial'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Stage Type', default='in_progress', help='Maps this stage to high-level treatment progress.')
    fold = fields.Boolean(string='Folded in Kanban', default=False)
    description = fields.Text(string='Description')


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    treatment_stage_ids = fields.One2many('dental.treatment.stage', 'treatment_id', string='Configured Stages')


class DentalTreatmentPlan(models.Model):
    _name = 'dental.treatment.plan'
    _description = 'Treatment Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'dental.company.mixin']

    name = fields.Char(string='Plan Number', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    patient_id = fields.Many2one('res.partner', string='Patient', required=True, domain=[('is_dental_patient', '=', True)], tracking=True)
    case_id = fields.Many2one('dental.case', string='Dental Case', tracking=True, check_company=True)
    doctor_id = fields.Many2one('hr.employee.public', string='Doctor', tracking=True)
    appointment_id = fields.Many2one('dental.appointment', string='Appointment', tracking=True, check_company=True)
    branch_id = fields.Many2one('res.company', string='Branch', related='appointment_id.branch_id', store=True)
    
    plan_date = fields.Date(string='Plan Date', default=fields.Date.context_today, required=True, tracking=True)
    notes = fields.Text(string='Notes')
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('proposed', 'Proposed'),
        ('approved', 'Approved'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)
    
    line_ids = fields.One2many('dental.treatment.plan.line', 'plan_id', string='Treatments')
    session_ids = fields.One2many('dental.treatment.session', 'plan_id', string='Sessions')

    # Patient acceptance (consent to the proposed treatment)
    accepted_date = fields.Datetime(string='Accepted On', readonly=True, copy=False, tracking=True)
    accepted_by_id = fields.Many2one('res.users', string='Acceptance Recorded By', readonly=True, copy=False)
    acceptance_note = fields.Text(string='Acceptance Note', copy=False,
                                  help='How the patient accepted the plan (verbal, signed form...) and any conditions.')
    accepted_amount = fields.Monetary(string='Accepted Total', compute='_compute_progress', store=True)
    progress = fields.Float(string='Progress (%)', compute='_compute_progress', store=True,
                            help='Share of the accepted treatment visits completed so far.')
    session_count = fields.Integer(string='Session Count', compute='_compute_session_count')
    estimated_total = fields.Monetary(string='Estimated Total', compute='_compute_total', store=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', depends=['company_id.currency_id'], store=True)

    step_count = fields.Integer(string='Steps', compute='_compute_step_summary')
    step_done_count = fields.Integer(string='Steps Done', compute='_compute_step_summary')
    step_summary = fields.Char(string='Steps Summary', compute='_compute_step_summary')

    @api.depends('session_ids')
    def _compute_session_count(self):
        for plan in self:
            plan.session_count = len(plan.session_ids)

    @api.depends('line_ids.state', 'line_ids.acceptance')
    def _compute_step_summary(self):
        for plan in self:
            steps = plan.line_ids.filtered(lambda l: l.state != 'cancelled' and l.acceptance != 'declined')
            done = steps.filtered(lambda l: l.state == 'completed')
            plan.step_count = len(steps)
            plan.step_done_count = len(done)
            plan.step_summary = _('%(done)s of %(total)s steps done', done=len(done), total=len(steps)) if steps else _('No steps yet')

    def action_open_form(self):
        """Open the plan on its own page (from the plan cards of the case)."""
        self.ensure_one()
        return {
            'name': self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'dental.treatment.plan',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('dental_core.view_dental_treatment_plan_form').id, 'form')],
            'target': 'current',
        }

    def action_view_sessions(self):
        self.ensure_one()
        return {
            'name': _('Treatment Sessions - %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.treatment.session',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', self.id)],
            'context': {
                'default_plan_id': self.id,
                'default_patient_id': self.patient_id.id,
                'default_doctor_id': self.doctor_id.id if self.doctor_id else False,
                'default_case_id': self.case_id.id if self.case_id else False,
            },
        }

    @api.depends('case_id.company_id', 'appointment_id.company_id')
    def _compute_company_id(self):
        self._set_company_from('case_id', 'appointment_id')

    @api.depends('line_ids.estimated_amount')
    def _compute_total(self):
        for plan in self:
            plan.estimated_total = sum(plan.line_ids.mapped('estimated_amount'))

    @api.depends('line_ids.acceptance', 'line_ids.state', 'line_ids.estimated_amount',
                 'line_ids.completed_visits', 'line_ids.number_of_visits')
    def _compute_progress(self):
        for plan in self:
            lines = plan.line_ids.filtered(lambda l: l.acceptance != 'declined' and l.state != 'cancelled')
            plan.accepted_amount = sum(lines.filtered(lambda l: l.acceptance == 'accepted').mapped('estimated_amount'))
            planned = sum(max(l.number_of_visits, 1) for l in lines)
            done = sum(max(l.number_of_visits, 1) if l.state == 'completed' else min(l.completed_visits, max(l.number_of_visits, 1))
                       for l in lines)
            plan.progress = round(done * 100.0 / planned, 1) if planned else 0.0

    def action_propose(self):
        for plan in self:
            if plan.state != 'draft':
                raise UserError(_("Only draft plans can be proposed to the patient."))
            if not plan.line_ids:
                raise UserError(_("Add at least one treatment before proposing plan %s.", plan.name))
        self.write({'state': 'proposed'})

    def action_accept(self):
        """Record the patient's acceptance. Treatments not explicitly declined are accepted."""
        for plan in self:
            if plan.state not in ('draft', 'proposed'):
                raise UserError(_("Plan %s is not awaiting acceptance.", plan.name))
            pending = plan.line_ids.filtered(lambda l: l.acceptance == 'pending' and l.state != 'cancelled')
            pending.write({'acceptance': 'accepted'})
            if not plan.line_ids.filtered(lambda l: l.acceptance == 'accepted'):
                raise UserError(_("Plan %s has no accepted treatment. Decline the plan instead.", plan.name))
            plan.write({'state': 'approved', 'accepted_date': fields.Datetime.now(), 'accepted_by_id': self.env.user.id})
            declined = plan.line_ids.filtered(lambda l: l.acceptance == 'declined')
            plan.message_post(body=_("Treatment plan accepted by the patient (%(accepted)s of %(total)s treatments).",
                                     accepted=len(plan.line_ids) - len(declined), total=len(plan.line_ids)))

    def action_decline(self):
        """The patient declined the whole plan. Completed work is kept; open work is cancelled."""
        for plan in self:
            if plan.state in ('completed', 'cancelled'):
                raise UserError(_("Plan %s is already closed.", plan.name))
            if plan.session_ids.filtered(lambda s: s.state == 'completed'):
                raise UserError(_("Treatment of plan %s has already been performed; decline the remaining "
                                  "treatments individually instead.", plan.name))
            plan.line_ids.filtered(lambda l: l.state != 'completed').write({'acceptance': 'declined', 'state': 'cancelled'})
            plan.session_ids.filtered(lambda s: s.state in ('planned', 'in_progress')).action_cancel()
            plan.state = 'cancelled'
            plan.message_post(body=_("Treatment plan declined by the patient."))

    def action_reset_to_draft(self):
        for plan in self:
            if plan.state not in ('proposed', 'cancelled'):
                raise UserError(_("Only proposed or cancelled plans can be reset to draft."))
            if plan.session_ids.filtered(lambda s: s.state == 'completed'):
                raise UserError(_("Plan %s already has performed treatment and cannot go back to draft.", plan.name))
        self.line_ids.filtered(lambda l: l.state == 'cancelled').write({'state': 'draft'})
        self.line_ids.write({'acceptance': 'pending'})
        self.write({'state': 'draft', 'accepted_date': False, 'accepted_by_id': False})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('dental.treatment.plan') or _('New')
        return super().create(vals_list)

    @api.onchange('case_id')
    def _onchange_case_id(self):
        case = self.case_id
        if not case:
            return
        if case.patient_id:
            self.patient_id = case.patient_id
        if not self.doctor_id and case.doctor_id:
            self.doctor_id = case.doctor_id
        if not self.appointment_id and case.appointment_id:
            self.appointment_id = case.appointment_id


class DentalTreatmentPlanLine(models.Model):
    _name = 'dental.treatment.plan.line'
    _description = 'Treatment Plan Line'
    _check_company_auto = True
    _order = 'phase, priority desc, id'

    plan_id = fields.Many2one('dental.treatment.plan', string='Treatment Plan', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='plan_id.company_id', store=True, index=True, string='Branch')
    case_id = fields.Many2one(related='plan_id.case_id', store=True, index=True, string='Dental Case')
    treatment_id = fields.Many2one('product.template', string='Treatment', domain=[('is_dental_treatment', '=', True)], required=True, check_company=True)
    tooth_reference = fields.Char(string='Tooth Reference')
    description = fields.Text(string='Description')
    
    quantity = fields.Float(string='Quantity', default=1.0, required=True)
    unit_price = fields.Float(string='Unit Price')
    discount = fields.Float(string='Discount (%)')
    estimated_amount = fields.Monetary(string='Estimated Amount', compute='_compute_amount', store=True)
    currency_id = fields.Many2one(related='plan_id.currency_id', depends=['plan_id.currency_id'], store=True)
    
    number_of_visits = fields.Integer(string='Number of Visits', default=1)
    visit_interval = fields.Char(
        string='Interval Between Visits',
        help='Time until the next visit after each completed session, e.g. 1 Week, 4 Weeks, 1 Month. '
             'Defaults to the interval set on the treatment, otherwise 1 week.')
    notes = fields.Text(string='Notes')

    phase = fields.Selection(TREATMENT_PHASES, string='Phase', default='3',
                             help='Sequencing of the plan: urgent care first, then disease control, '
                                  'definitive treatment and maintenance.')
    priority = fields.Selection(TREATMENT_PRIORITIES, string='Priority', default='0')
    acceptance = fields.Selection([
        ('pending', 'Awaiting Decision'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
    ], string='Patient Decision', default='pending', required=True, copy=False)
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('planned', 'Planned'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft')
    
    session_ids = fields.One2many('dental.treatment.session', 'plan_line_id', string='Sessions')
    completed_visits = fields.Integer(string='Completed Visits', compute='_compute_completed_visits')

    stage_id = fields.Many2one(
        'dental.treatment.stage',
        string='Stage',
        tracking=True,
        domain="['|', ('treatment_id', '=', False), ('treatment_id', '=', treatment_id)]",
        default=lambda self: self._default_stage_id(),
    )
    stage_sequence = fields.Integer(related='stage_id.sequence', string='Stage Sequence', store=True)
    progress = fields.Float(string='Progress (%)', compute='_compute_progress', store=True)
    progress_summary = fields.Char(string='Progress', compute='_compute_progress_summary')

    @api.constrains('number_of_visits', 'quantity', 'discount')
    def _check_amounts(self):
        for line in self:
            if line.number_of_visits < 1:
                raise ValidationError(_("A treatment needs at least one visit."))
            if line.quantity <= 0:
                raise ValidationError(_("Quantity must be positive."))
            if not 0.0 <= line.discount <= 100.0:
                raise ValidationError(_("Discount must be between 0 and 100%."))

    @api.constrains('tooth_reference')
    def _check_tooth_reference(self):
        from .dental_tooth_finding import TOOTH_NAMES
        for line in self.filtered('tooth_reference'):
            teeth = [t.strip() for t in line.tooth_reference.replace(';', ',').split(',') if t.strip()]
            invalid = [t for t in teeth if t not in TOOTH_NAMES]
            if invalid:
                raise ValidationError(_("Invalid tooth number(s) %(teeth)s. Use FDI notation, e.g. 36 or 11, 21.",
                                        teeth=', '.join(invalid)))

    def action_accept_line(self):
        self._check_decision_allowed()
        self.write({'acceptance': 'accepted'})

    def action_decline_line(self):
        self._check_decision_allowed()
        if self.session_ids.filtered(lambda s: s.state == 'completed'):
            raise UserError(_("This treatment has already been (partly) performed and cannot be declined."))
        self.write({'acceptance': 'declined', 'state': 'cancelled'})
        self.session_ids.filtered(lambda s: s.state in ('planned', 'in_progress')).action_cancel()
        self._update_progress_from_sessions()

    def _check_decision_allowed(self):
        for line in self:
            if line.plan_id.state in ('completed', 'cancelled') or line.state == 'completed':
                raise UserError(_("The decision on a closed treatment can no longer be changed."))

    def _ensure_can_perform(self):
        """Backend guard: declined treatment is never performed or billed."""
        for line in self:
            if line.acceptance == 'declined' or line.state == 'cancelled':
                raise UserError(_("%s was declined or cancelled and cannot be performed.", line.display_name))
            if line.plan_id.state in ('completed', 'cancelled'):
                raise UserError(_("Plan %s is closed.", line.plan_id.name))

    @api.model
    def _default_stage_id(self):
        return self.env['dental.treatment.stage'].search(
            [('treatment_id', '=', False)], order='sequence, id', limit=1
        )

    @api.depends('completed_visits', 'number_of_visits', 'state')
    def _compute_progress(self):
        for line in self:
            if line.state == 'completed':
                line.progress = 100.0
            elif line.state == 'cancelled':
                line.progress = 0.0
            elif line.number_of_visits > 0:
                pct = (line.completed_visits / line.number_of_visits) * 100.0
                line.progress = min(max(round(pct, 1), 0.0), 100.0)
            else:
                line.progress = 0.0

    @api.depends('completed_visits', 'number_of_visits')
    def _compute_progress_summary(self):
        for line in self:
            total = max(line.number_of_visits, 1)
            line.progress_summary = _('%(done)s of %(total)s visits completed', done=line.completed_visits, total=total)

    @api.depends('quantity', 'unit_price', 'discount')
    def _compute_amount(self):
        for line in self:
            price = line.quantity * line.unit_price
            discount_amount = price * (line.discount / 100.0)
            line.estimated_amount = price - discount_amount

    @api.depends('session_ids.state')
    def _compute_completed_visits(self):
        for line in self:
            line.completed_visits = len(line.session_ids.filtered(lambda s: s.state == 'completed'))

    @api.depends('treatment_id', 'tooth_reference', 'plan_id.name')
    def _compute_display_name(self):
        for line in self:
            name = line.treatment_id.name or _('Treatment')
            if line.tooth_reference:
                name = _('%(treatment)s – Tooth %(tooth)s', treatment=name, tooth=line.tooth_reference)
            if line.plan_id.name:
                name = f"{name} ({line.plan_id.name})"
            line.display_name = name

    def action_add_session(self):
        """Add a new treatment session under this planned treatment."""
        self.ensure_one()
        self._ensure_can_perform()
        plan = self.plan_id
        case = plan.case_id
        doctor = plan.doctor_id or (case.doctor_id if case else False)
        if not doctor and hasattr(self.env.user, 'employee_ids') and self.env.user.employee_ids:
            doctor = self.env.user.employee_ids[0]
        appointment = (case.current_visit_id if case else False) or plan.appointment_id or (case.appointment_id if case else False)

        session = self.env['dental.treatment.session'].create({
            'patient_id': plan.patient_id.id,
            'case_id': case.id if case else False,
            'plan_id': plan.id,
            'plan_line_id': self.id,
            'doctor_id': doctor.id if doctor else False,
            'appointment_id': appointment.id if appointment else False,
            'tooth_reference': self.tooth_reference,
            'stage_id': self.stage_id.id if self.stage_id else False,
            'session_date': fields.Datetime.now(),
            'state': 'planned',
        })
        if self.state == 'draft':
            self.state = 'planned'
        if plan.state in ('draft', 'proposed'):
            plan.state = 'in_progress'
        return {
            'name': _('Treatment Session'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.treatment.session',
            'res_id': session.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_mark_visit_done(self):
        """One-click recording that the doctor performed (a visit of) this treatment; makes it billable."""
        session_obj = self.env['dental.treatment.session']
        self.filtered(lambda l: l.state != 'completed')._ensure_can_perform()
        for line in self.filtered(lambda l: l.state not in ('completed', 'cancelled')):
            plan = line.plan_id
            case = plan.case_id
            session = line.session_ids.filtered(lambda s: s.state in ('planned', 'in_progress'))[:1]
            if not session:
                session = session_obj.create({
                    'patient_id': plan.patient_id.id,
                    'case_id': case.id if case else False,
                    'plan_id': plan.id,
                    'plan_line_id': line.id,
                    'doctor_id': (plan.doctor_id or (case.doctor_id if case else False)).id if (plan.doctor_id or (case.doctor_id if case else False)) else False,
                    'appointment_id': ((case.current_visit_id or plan.appointment_id) if case else plan.appointment_id).id if ((case.current_visit_id or plan.appointment_id) if case else plan.appointment_id) else False,
                    'tooth_reference': line.tooth_reference,
                    'stage_id': line.stage_id.id if line.stage_id else False,
                })
            session.action_complete()

    def _update_progress_from_sessions(self):
        """Advance line and plan status from the sessions completed so far."""
        for line in self:
            if line.state == 'cancelled':
                continue
            if line.completed_visits >= max(line.number_of_visits, 1):
                line.state = 'completed'
                completed_stage = self.env['dental.treatment.stage'].search([
                    ('stage_type', '=', 'completed'),
                    '|', ('treatment_id', '=', False), ('treatment_id', '=', line.treatment_id.id)
                ], order='sequence desc, id desc', limit=1)
                if completed_stage:
                    line.stage_id = completed_stage
            elif line.session_ids.filtered(lambda s: s.state in ('in_progress', 'completed')):
                line.state = 'in_progress'
                if not line.stage_id or line.stage_id.stage_type == 'planned':
                    prog_stage = self.env['dental.treatment.stage'].search([
                        ('stage_type', '=', 'in_progress'),
                        '|', ('treatment_id', '=', False), ('treatment_id', '=', line.treatment_id.id)
                    ], order='sequence, id', limit=1)
                    if prog_stage:
                        line.stage_id = prog_stage
        for plan in self.mapped('plan_id'):
            active_lines = plan.line_ids.filtered(lambda l: l.state != 'cancelled' and l.acceptance != 'declined')
            if active_lines and all(l.state == 'completed' for l in active_lines):
                plan.state = 'completed'
            elif plan.state in ('draft', 'proposed', 'approved') and any(l.state in ('in_progress', 'completed') for l in active_lines):
                plan.state = 'in_progress'

    @api.onchange('treatment_id')
    def _onchange_treatment_id(self):
        if self.treatment_id:
            self.description = self.treatment_id.name
            self.unit_price = self.treatment_id.list_price
            if self.treatment_id.number_of_visits:
                self.number_of_visits = self.treatment_id.number_of_visits
            self.visit_interval = self.treatment_id.visit_interval
            stage = self.env['dental.treatment.stage'].search([
                ('treatment_id', '=', self.treatment_id.id)
            ], order='sequence, id', limit=1)
            if not stage:
                stage = self.env['dental.treatment.stage'].search([
                    ('treatment_id', '=', False)
                ], order='sequence, id', limit=1)
            if stage:
                self.stage_id = stage


class DentalTreatmentSession(models.Model):
    _name = 'dental.treatment.session'
    _description = 'Treatment Session'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'dental.company.mixin']

    name = fields.Char(string='Session Number', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    patient_id = fields.Many2one('res.partner', string='Patient', required=True, domain=[('is_dental_patient', '=', True)], tracking=True)
    case_id = fields.Many2one('dental.case', string='Dental Case', tracking=True, check_company=True)
    plan_id = fields.Many2one('dental.treatment.plan', string='Treatment Plan', tracking=True, check_company=True)
    plan_line_id = fields.Many2one('dental.treatment.plan.line', string='Treatment Plan Line', required=True, tracking=True, check_company=True)

    doctor_id = fields.Many2one('hr.employee.public', string='Doctor', tracking=True)
    appointment_id = fields.Many2one('dental.appointment', string='Appointment', tracking=True, check_company=True)

    @api.depends('plan_line_id.company_id', 'case_id.company_id', 'appointment_id.company_id')
    def _compute_company_id(self):
        self._set_company_from('plan_line_id', 'case_id', 'appointment_id')
    
    session_date = fields.Datetime(string='Session Date', default=fields.Datetime.now, required=True, tracking=True)
    tooth_reference = fields.Char(string='Tooth Reference')
    stage_id = fields.Many2one(
        'dental.treatment.stage',
        string='Stage',
        tracking=True,
        domain="['|', ('treatment_id', '=', False), ('treatment_id', '=', plan_line_id.treatment_id)]",
    )
    
    procedure_notes = fields.Text(string='Procedure Notes')
    clinical_notes = fields.Text(string='Clinical Notes')

    # Planned (from the plan line) vs. actually performed
    planned_treatment_id = fields.Many2one(related='plan_line_id.treatment_id', string='Planned Treatment')
    planned_tooth_reference = fields.Char(related='plan_line_id.tooth_reference', string='Planned Tooth')
    performed_treatment_id = fields.Many2one('product.template', string='Performed Treatment',
                                             domain=[('is_dental_treatment', '=', True)], tracking=True,
                                             help='Leave empty when the planned treatment was performed as planned.')
    performed_tooth_reference = fields.Char(string='Performed On Tooth', tracking=True,
                                            help='Leave empty when performed on the planned tooth.')
    deviates_from_plan = fields.Boolean(string='Differs From Plan', compute='_compute_deviates_from_plan', store=True)
    deviation_reason = fields.Text(string='Reason for Change', tracking=True)
    
    state = fields.Selection([
        ('planned', 'Planned'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='planned', tracking=True)

    follow_up_ids = fields.One2many('dental.follow.up', 'session_id', string='Follow-ups')
    follow_up_count = fields.Integer(string='Follow-up Count', compute='_compute_follow_up_count')

    invoice_line_ids = fields.One2many('account.move.line', 'dental_session_id', string='Invoice Lines', readonly=True)
    billing_state = fields.Selection([
        ('not_billable', 'Not Billable'),
        ('to_invoice', 'To Invoice'),
        ('invoiced', 'Invoiced'),
    ], string='Billing', compute='_compute_billing_state')

    @api.depends('performed_treatment_id', 'performed_tooth_reference', 'plan_line_id.treatment_id', 'tooth_reference')
    def _compute_deviates_from_plan(self):
        for session in self:
            planned_tooth = session.tooth_reference or session.plan_line_id.tooth_reference or ''
            session.deviates_from_plan = bool(
                (session.performed_treatment_id and session.performed_treatment_id != session.plan_line_id.treatment_id)
                or (session.performed_tooth_reference and session.performed_tooth_reference.replace(' ', '') != planned_tooth.replace(' ', '')))

    @api.constrains('performed_tooth_reference')
    def _check_performed_tooth(self):
        from .dental_tooth_finding import TOOTH_NAMES
        for session in self.filtered('performed_tooth_reference'):
            teeth = [t.strip() for t in session.performed_tooth_reference.replace(';', ',').split(',') if t.strip()]
            invalid = [t for t in teeth if t not in TOOTH_NAMES]
            if invalid:
                raise ValidationError(_("Invalid tooth number(s) %(teeth)s. Use FDI notation, e.g. 36 or 11, 21.",
                                        teeth=', '.join(invalid)))

    @api.depends('state', 'invoice_line_ids.move_id.state')
    def _compute_billing_state(self):
        for session in self:
            if session._get_active_invoice_lines():
                session.billing_state = 'invoiced'
            elif session.state == 'completed':
                session.billing_state = 'to_invoice'
            else:
                session.billing_state = 'not_billable'

    def _get_active_invoice_lines(self):
        """Invoice lines that still bill this session; cancelled invoices release it for re-billing."""
        return self.sudo().invoice_line_ids.filtered(lambda l: l.move_id.state != 'cancel')

    def _get_billing_price(self, billed_in_batch=None):
        """Equal share of the plan line per visit; the final visit settles the remainder so totals match the plan.

        billed_in_batch: sessions of the same invoice already priced before this one.
        """
        self.ensure_one()
        line = self.plan_line_id
        currency = line.currency_id or self.env.company.currency_id
        visits = max(line.number_of_visits, 1)
        share = currency.round(line.estimated_amount / visits)
        batch_before = (billed_in_batch or self.browse()).filtered(lambda s: s.plan_line_id == line) - self
        other_billed = (line.session_ids - self - batch_before).filtered(lambda s: s._get_active_invoice_lines())
        already_billed = sum(other_billed._get_active_invoice_lines().mapped('price_subtotal')) + share * len(batch_before)
        if len(other_billed) + len(batch_before) + 1 >= visits:
            return max(currency.round(line.estimated_amount - already_billed), 0.0)
        return share

    def _prepare_invoice_line_vals(self, billed_in_batch=None):
        self.ensure_one()
        line = self.plan_line_id
        label = line.treatment_id.name or self.name
        tooth = self.tooth_reference or line.tooth_reference
        if tooth:
            label = _('%(treatment)s – Tooth %(tooth)s', treatment=label, tooth=tooth)
        if line.number_of_visits > 1:
            visit_no = len(line.session_ids.filtered(lambda s: s.state == 'completed' and s.session_date <= self.session_date))
            label = _('%(label)s – Visit %(n)s/%(total)s', label=label, n=visit_no, total=line.number_of_visits)
        return {
            'product_id': line.treatment_id.product_variant_id.id,
            'name': f"{label} ({self.name})",
            'quantity': 1.0,
            'price_unit': self._get_billing_price(billed_in_batch),
            'dental_session_id': self.id,
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('dental.treatment.session') or _('New')
            if vals.get('plan_line_id'):
                line = self.env['dental.treatment.plan.line'].browse(vals['plan_line_id'])
                if line.exists():
                    plan = line.plan_id
                    case = plan.case_id
                    if not vals.get('plan_id'):
                        vals['plan_id'] = plan.id
                    if not vals.get('patient_id') and plan.patient_id:
                        vals['patient_id'] = plan.patient_id.id
                    if not vals.get('case_id') and case:
                        vals['case_id'] = case.id
                    if not vals.get('doctor_id'):
                        doc = plan.doctor_id or (case.doctor_id if case else False)
                        if doc:
                            vals['doctor_id'] = doc.id
                    if not vals.get('appointment_id'):
                        appt = (case.current_visit_id if case else False) or plan.appointment_id or (case.appointment_id if case else False)
                        if appt:
                            vals['appointment_id'] = appt.id
                    if not vals.get('tooth_reference') and line.tooth_reference:
                        vals['tooth_reference'] = line.tooth_reference
                    if not vals.get('stage_id') and line.stage_id:
                        vals['stage_id'] = line.stage_id.id
        return super().create(vals_list)

    @api.depends('follow_up_ids')
    def _compute_follow_up_count(self):
        for session in self:
            session.follow_up_count = len(session.follow_up_ids)

    def action_start(self):
        sessions = self.filtered(lambda s: s.state == 'planned')
        sessions.mapped('plan_line_id')._ensure_can_perform()
        sessions.write({'state': 'in_progress'})
        sessions.mapped('plan_line_id')._update_progress_from_sessions()
        sessions._mark_case_under_treatment()

    def action_complete(self):
        sessions = self.filtered(lambda s: s.state in ('planned', 'in_progress'))
        sessions.mapped('plan_line_id')._ensure_can_perform()
        for session in sessions:
            if session.deviates_from_plan and not (session.deviation_reason or '').strip():
                raise ValidationError(_("%s: the performed treatment differs from the plan; record the reason for "
                                        "the change before completing the session.", session.name))
        # Performing a treatment still awaiting the patient's decision records it as accepted
        sessions.mapped('plan_line_id').filtered(lambda l: l.acceptance == 'pending').write({'acceptance': 'accepted'})
        sessions.write({'state': 'completed'})
        for session in sessions:
            if session.stage_id and session.plan_line_id:
                session.plan_line_id.stage_id = session.stage_id
        sessions.mapped('plan_line_id')._update_progress_from_sessions()
        sessions._mark_case_under_treatment()
        sessions._schedule_follow_up()

    def _mark_case_under_treatment(self):
        self.mapped('case_id').filtered(lambda c: c.state in ('draft', 'open')).write({'state': 'under_treatment'})

    def action_cancel(self):
        sessions = self.filtered(lambda s: s.state != 'completed')
        sessions.write({'state': 'cancelled'})
        sessions.follow_up_ids.filtered(lambda f: f.state == 'pending').action_cancel()

    def action_reset_to_planned(self):
        self.filtered(lambda s: s.state == 'cancelled').write({'state': 'planned'})

    def _schedule_follow_up(self):
        """Book the next visit while the treatment is ongoing, otherwise a post-treatment review."""
        follow_up_obj = self.env['dental.follow.up'].sudo()
        for session in self:
            if session.follow_up_ids.filtered(lambda f: f.state == 'pending'):
                continue
            line = session.plan_line_id
            treatment = line.treatment_id
            label = treatment.name or session.name
            tooth = session.tooth_reference or line.tooth_reference
            if tooth:
                label = _('%(treatment)s (Tooth %(tooth)s)', treatment=label, tooth=tooth)

            if line.state != 'completed':
                # Multi-visit treatments (e.g. monthly braces adjustments): the line's interval, then the treatment's
                days = (follow_up_obj._parse_interval_days(line.visit_interval)
                        or follow_up_obj._parse_interval_days(treatment.visit_interval) or 7)
                follow_up_type = 'next_visit'
                priority = '1'
                reason = _('Visit %(next)s of %(total)s: %(treatment)s',
                           next=line.completed_visits + 1, total=line.number_of_visits, treatment=label)
            else:
                days, reason = follow_up_obj._suggest_followup(treatment, session.name)
                # A clinic-configured interval on the treatment overrides the clinical default
                days = follow_up_obj._parse_interval_days(treatment.followup_interval) or days
                follow_up_type = 'review'
                priority = '0'
                if tooth:
                    reason = _('%(reason)s (Tooth %(tooth)s)', reason=reason, tooth=tooth)

            session_day = fields.Datetime.context_timestamp(session, session.session_date).date()
            follow_up_obj.create({
                'patient_id': session.patient_id.id,
                'case_id': session.case_id.id if session.case_id else False,
                'treatment_plan_id': session.plan_id.id or line.plan_id.id,
                'plan_line_id': line.id,
                'session_id': session.id,
                'appointment_id': session.appointment_id.id if session.appointment_id else False,
                # Session doctor is hr.employee.public; follow-ups use hr.employee (same ids)
                'doctor_id': session.doctor_id.id if session.doctor_id else False,
                'treatment_id': treatment.id,
                'tooth_reference': tooth,
                'follow_up_type': follow_up_type,
                'priority': priority,
                'date': session_day + timedelta(days=days),
                'reason': reason,
                'state': 'pending',
                'notes': _('Auto-scheduled after treatment session %(session)s on %(date)s.',
                           session=session.name, date=session_day),
            })
            session.message_post(body=_('Follow-up scheduled for %s.', session_day + timedelta(days=days)))

    def action_view_follow_ups(self):
        self.ensure_one()
        return {
            'name': _('Follow-ups'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.follow.up',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {'default_session_id': self.id, 'default_patient_id': self.patient_id.id},
        }

    @api.onchange('plan_line_id')
    def _onchange_plan_line_id(self):
        if self.plan_line_id:
            self.tooth_reference = self.plan_line_id.tooth_reference
            if self.plan_line_id.stage_id:
                self.stage_id = self.plan_line_id.stage_id
            plan = self.plan_line_id.plan_id
            if plan:
                self.plan_id = plan
                self.patient_id = plan.patient_id
                if plan.case_id:
                    self.case_id = plan.case_id
                if not self.doctor_id and plan.doctor_id:
                    self.doctor_id = plan.doctor_id

    @api.onchange('case_id')
    def _onchange_case_id(self):
        case = self.case_id
        if not case:
            return
        if case.patient_id:
            self.patient_id = case.patient_id
        if not self.doctor_id and case.doctor_id:
            self.doctor_id = case.doctor_id
        if not self.appointment_id and case.appointment_id:
            self.appointment_id = case.appointment_id
        if not self.plan_id and case._origin.id:
            plans = self.env['dental.treatment.plan'].search(
                [('case_id', '=', case._origin.id), ('state', 'not in', ('completed', 'cancelled'))],
                order='plan_date desc, id desc',
                limit=1,
            )
            self.plan_id = plans
