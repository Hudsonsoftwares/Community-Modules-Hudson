# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import html2plaintext

STATES = [
    ('draft', 'Draft'),
    ('submitted', 'Awaiting Specialist'),
    ('in_review', 'Under Review'),
    ('info_requested', 'Information Requested'),
    ('opinion_submitted', 'Opinion Submitted'),
    ('clarification', 'Clarification Requested'),
    ('closed', 'Decision Recorded'),
    ('declined', 'Declined'),
    ('cancelled', 'Cancelled'),
]
# States in which the request is still waiting on someone
OPEN_STATES = ('submitted', 'in_review', 'info_requested', 'opinion_submitted', 'clarification')
# States in which the assigned specialist may read the request and the shared clinical records
SPECIALIST_VISIBLE_STATES = OPEN_STATES + ('closed', 'declined')

RECOMMENDED_ACTIONS = [
    ('agree', 'Agree with the proposed plan'),
    ('modify', 'Modify the proposed plan'),
    ('alternative', 'Alternative treatment recommended'),
    ('investigate', 'Further investigation required'),
    ('refer', 'Refer to another specialist'),
    ('no_treatment', 'No treatment required'),
]

DECISIONS = [
    ('accepted', 'Recommendation accepted'),
    ('partially_accepted', 'Partially accepted'),
    ('not_accepted', 'Not accepted'),
    ('referred', 'Referred elsewhere'),
]

ACTIVITY_TYPE = 'dental_second_opinion.mail_activity_type_second_opinion'
SPECIALIST_GROUP = 'dental_second_opinion.group_dental_specialist'
MANAGER_GROUP = 'dental_base.group_dental_manager'


class DentalSecondOpinion(models.Model):
    _name = 'dental.second.opinion'
    _description = 'Clinical Second Opinion Request'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'dental.company.mixin']
    _order = 'priority desc, request_date desc, id desc'

    # Set only by the workflow methods (which validate the user's role, then write with sudo)
    _WORKFLOW_FIELDS = frozenset({
        'name', 'state', 'requesting_user_id', 'company_id', 'submitted_date', 'review_start_date', 'opinion_date',
        'closed_date', 'info_request_note', 'clarification_note', 'decline_reason', 'opinion_revision',
        'decision', 'decision_notes', 'decided_by_id', 'decision_date',
    })
    # Editable by the requesting dentist (or a clinic manager) while the request is with them
    _REQUEST_FIELDS = frozenset({
        'case_id', 'requesting_doctor_id', 'specialist_id', 'priority', 'due_date', 'clinical_question',
        'clinical_summary', 'examination_ids', 'diagnosis_ids', 'document_ids', 'treatment_plan_id',
        'request_attachment_ids',
    })
    _REQUEST_EDIT_STATES = ('draft', 'info_requested')
    # Editable by the assigned specialist only, while the review is with them
    _OPINION_FIELDS = frozenset({'findings', 'recommendations', 'recommended_action', 'opinion_attachment_ids'})
    _OPINION_EDIT_STATES = ('in_review', 'clarification')

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    state = fields.Selection(STATES, string='Status', default='draft', required=True, readonly=True, copy=False,
                             tracking=True, index=True, group_expand='_group_expand_states')
    priority = fields.Selection([('0', 'Routine'), ('1', 'Urgent'), ('2', 'Emergency')], string='Priority',
                                default='0', tracking=True)
    request_date = fields.Datetime(string='Requested On', default=fields.Datetime.now, required=True, readonly=True, copy=False)
    due_date = fields.Date(string='Response Needed By', tracking=True)

    # --- Reused clinical records -------------------------------------------------------------
    case_id = fields.Many2one('dental.case', string='Dental Case', required=True, index=True, ondelete='restrict',
                              tracking=True, check_company=True)
    patient_id = fields.Many2one(related='case_id.patient_id', string='Patient', store=True, index=True)
    requesting_doctor_id = fields.Many2one(
        'hr.employee.public', string='Requesting Dentist', tracking=True,
        compute='_compute_requesting_doctor_id', store=True, readonly=False, precompute=True,
        domain=[('is_dentist', '=', True)])
    requesting_user_id = fields.Many2one('res.users', string='Requested By', required=True, readonly=True, index=True,
                                         default=lambda self: self.env.user, copy=False)
    specialist_id = fields.Many2one('hr.employee.public', string='Specialist', tracking=True, index=True,
                                    domain="[('id', 'in', eligible_specialist_ids)]")
    specialist_user_id = fields.Many2one(related='specialist_id.user_id', string='Specialist User', store=True, index=True)
    specialization = fields.Char(related='specialist_id.specialization', string='Specialization')
    eligible_specialist_ids = fields.Many2many('hr.employee.public', compute='_compute_eligible_specialist_ids')

    clinical_question = fields.Text(string='Clinical Question', tracking=True,
                                    help='What the specialist is asked to answer.')
    clinical_summary = fields.Text(string='Case Summary for the Specialist')
    examination_ids = fields.Many2many('dental.clinical.examination', 'dental_second_opinion_examination_rel',
                                       'request_id', 'examination_id', string='Consultations', check_company=True,
                                       domain="[('case_id', '=', case_id)]")
    diagnosis_ids = fields.Many2many('dental.patient.diagnosis', 'dental_second_opinion_diagnosis_rel',
                                     'request_id', 'diagnosis_id', string='Diagnoses', check_company=True,
                                     domain="[('case_id', '=', case_id)]")
    document_ids = fields.Many2many('dental.patient.document', 'dental_second_opinion_document_rel',
                                    'request_id', 'document_id', string='X-Rays & Documents', check_company=True,
                                    domain="[('patient_id', '=', patient_id)]")
    treatment_plan_id = fields.Many2one('dental.treatment.plan', string='Proposed Treatment Plan', check_company=True,
                                        domain="[('case_id', '=', case_id)]",
                                        help='Shared for reference only. This module never changes treatment plans.')
    request_attachment_ids = fields.Many2many('ir.attachment', 'dental_second_opinion_request_attachment_rel',
                                              'request_id', 'attachment_id', string='Additional Files')

    # Read-only snapshot of the case, so the specialist reviews it without opening the dentist's workspace
    chief_complaint = fields.Text(related='case_id.chief_complaint', string='Chief Complaint')
    case_clinical_notes = fields.Text(related='case_id.clinical_notes', string='Clinical Notes')
    medical_history_summary = fields.Text(related='case_id.medical_history_summary')
    dental_history_summary = fields.Text(related='case_id.dental_history_summary')
    allergies = fields.Text(related='case_id.allergies')
    current_medications = fields.Text(related='case_id.current_medications')
    treatment_plan_line_ids = fields.One2many(related='treatment_plan_id.line_ids', string='Planned Treatments')

    # --- Specialist opinion ----------------------------------------------------------------------
    findings = fields.Html(string='Findings', sanitize=True)
    recommendations = fields.Html(string='Recommendations', sanitize=True)
    recommended_action = fields.Selection(RECOMMENDED_ACTIONS, string='Recommended Action', tracking=True)
    opinion_attachment_ids = fields.Many2many('ir.attachment', 'dental_second_opinion_opinion_attachment_rel',
                                              'request_id', 'attachment_id', string='Specialist Attachments')
    opinion_revision = fields.Integer(string='Opinion Revision', readonly=True, copy=False)

    # --- Exchanges (latest; full history in the audit log) ---------------------------------------
    info_request_note = fields.Text(string='Information Requested by Specialist', readonly=True, copy=False)
    clarification_note = fields.Text(string='Clarification Requested by Dentist', readonly=True, copy=False)
    decline_reason = fields.Text(string='Decline Reason', readonly=True, copy=False)

    # --- Final clinical decision -----------------------------------------------------------------
    decision = fields.Selection(DECISIONS, string='Clinical Decision', readonly=True, copy=False, tracking=True)
    decision_notes = fields.Text(string='Decision Notes', readonly=True, copy=False)
    decided_by_id = fields.Many2one('res.users', string='Decided By', readonly=True, copy=False)
    decision_date = fields.Datetime(string='Decided On', readonly=True, copy=False)

    # --- Tracking --------------------------------------------------------------------------------
    submitted_date = fields.Datetime(string='Sent On', readonly=True, copy=False)
    review_start_date = fields.Datetime(string='Review Started', readonly=True, copy=False)
    opinion_date = fields.Datetime(string='Opinion Received', readonly=True, copy=False)
    closed_date = fields.Datetime(string='Closed On', readonly=True, copy=False)
    turnaround_hours = fields.Float(string='Turnaround (h)', compute='_compute_turnaround_hours', store=True,
                                    aggregator='avg', help='Hours from sending the request to the first specialist opinion.')
    is_overdue = fields.Boolean(string='Overdue', compute='_compute_is_overdue', search='_search_is_overdue')
    log_ids = fields.One2many('dental.second.opinion.log', 'request_id', string='Audit History', readonly=True)

    # Role flags for the form buttons
    is_requester = fields.Boolean(compute='_compute_user_role')
    is_specialist = fields.Boolean(compute='_compute_user_role')

    @api.model
    def _group_expand_states(self, states, domain):
        return [key for key, _label in STATES if key not in ('cancelled',)]

    @api.depends('case_id.company_id')
    def _compute_company_id(self):
        self._set_company_from('case_id')

    @api.depends('case_id')
    def _compute_requesting_doctor_id(self):
        for request in self:
            if request.requesting_doctor_id:
                continue
            # Dentists usually have no HR rights on hr.employee itself
            employee = self.env.user.sudo().employee_id
            request.requesting_doctor_id = (
                employee.id if employee and employee.is_dentist else request.case_id.doctor_id.id) or False

    @api.depends('company_id', 'requesting_user_id')
    def _compute_eligible_specialist_ids(self):
        specialist_users = self.env.ref(SPECIALIST_GROUP).sudo().all_user_ids.filtered('active')
        employees = self.env['hr.employee.public'].sudo().search([('user_id', 'in', specialist_users.ids)])
        for request in self:
            company = request.company_id or self.env.company
            request.eligible_specialist_ids = employees.filtered(
                lambda e: company in e.user_id.company_ids and e.user_id != request.requesting_user_id)

    @api.depends('submitted_date', 'opinion_date')
    def _compute_turnaround_hours(self):
        for request in self:
            if request.submitted_date and request.opinion_date:
                request.turnaround_hours = (request.opinion_date - request.submitted_date).total_seconds() / 3600.0
            else:
                request.turnaround_hours = 0.0

    @api.depends('due_date', 'state')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for request in self:
            request.is_overdue = bool(request.due_date and request.due_date < today and request.state in OPEN_STATES)

    def _search_is_overdue(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_('Unsupported search on Overdue.'))
        domain = [('due_date', '<', fields.Date.context_today(self)), ('state', 'in', OPEN_STATES)]
        positive = (operator == '=') == value
        return domain if positive else ['!', '&', *domain]

    @api.depends_context('uid')
    @api.depends('requesting_user_id', 'specialist_user_id')
    def _compute_user_role(self):
        manager = self._is_so_manager()
        for request in self:
            request.is_requester = manager or request.requesting_user_id == self.env.user
            request.is_specialist = request.specialist_user_id == self.env.user

    # ------------------------------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------------------------------

    @api.constrains('specialist_id', 'requesting_user_id', 'company_id')
    def _check_specialist(self):
        group = self.env.ref(SPECIALIST_GROUP)
        for request in self.sudo():
            user = request.specialist_id.user_id
            if not request.specialist_id:
                continue
            if not user:
                raise ValidationError(_('%s has no user account and cannot review requests.', request.specialist_id.name))
            if group not in user.all_group_ids:
                raise ValidationError(_('%s is not a Second Opinion Specialist.', request.specialist_id.name))
            if user == request.requesting_user_id:
                raise ValidationError(_('You cannot request a second opinion from yourself.'))
            if request.company_id not in user.company_ids:
                raise ValidationError(_('%(specialist)s has no access to branch %(branch)s.',
                                        specialist=request.specialist_id.name, branch=request.company_id.name))

    @api.constrains('case_id', 'examination_ids', 'diagnosis_ids', 'document_ids', 'treatment_plan_id')
    def _check_shared_records(self):
        for request in self.sudo():
            case = request.case_id
            if request.examination_ids.filtered(lambda r: r.case_id != case):
                raise ValidationError(_('Shared consultations must belong to case %s.', case.name))
            if request.diagnosis_ids.filtered(lambda r: r.case_id != case):
                raise ValidationError(_('Shared diagnoses must belong to case %s.', case.name))
            if request.treatment_plan_id and request.treatment_plan_id.case_id != case:
                raise ValidationError(_('The treatment plan must belong to case %s.', case.name))
            if request.document_ids.filtered(lambda r: r.patient_id != case.patient_id):
                raise ValidationError(_('Shared X-rays and documents must belong to patient %s.', case.patient_id.name))

    # ------------------------------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            manager = self._is_so_manager()
            for vals in vals_list:
                for fname in self._WORKFLOW_FIELDS - {'company_id'}:
                    vals.pop(fname, None)
                if not manager:
                    vals['requesting_user_id'] = self.env.user.id
                # The requester must be able to see the case they share
                if vals.get('case_id'):
                    self.env['dental.case'].browse(vals['case_id']).check_access('read')
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('dental.second.opinion') or _('New')
        requests = super().create(vals_list)
        for request in requests:
            request._log_event('created')
        return requests

    def write(self, vals):
        if not self.env.su:
            self._check_user_write(set(vals))
        return super().write(vals)

    def _check_user_write(self, fnames):
        """Keep the requester's case data, the specialist's opinion and the workflow apart."""
        if fnames & self._WORKFLOW_FIELDS:
            raise UserError(_('Use the workflow buttons to change the status, decision or exchanges of a second opinion.'))
        manager = self._is_so_manager()
        for request in self:
            if fnames & self._REQUEST_FIELDS:
                if not (manager or request.requesting_user_id == self.env.user):
                    raise AccessError(_('Only the requesting dentist can change the request %s.', request.name))
                if request.state not in self._REQUEST_EDIT_STATES:
                    raise UserError(_('Request %s can no longer be changed in status "%s".',
                                      request.name, dict(STATES)[request.state]))
                if 'specialist_id' in fnames and request.state != 'draft':
                    raise UserError(_('Reassign the specialist from a draft request (reset declined requests to draft first).'))
                if 'case_id' in fnames and request.state != 'draft':
                    raise UserError(_('The dental case of a sent request cannot be changed.'))
            if fnames & self._OPINION_FIELDS:
                if request.specialist_user_id != self.env.user:
                    raise AccessError(_('Only the assigned specialist can write the opinion of %s.', request.name))
                if request.state not in self._OPINION_EDIT_STATES:
                    raise UserError(_('Start the review before writing the opinion of %s.', request.name))

    def unlink(self):
        if any(request.state != 'draft' for request in self):
            raise UserError(_('Only draft second opinion requests can be deleted; cancel the others to keep the audit trail.'))
        return super().unlink()

    # ------------------------------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------------------------------

    @api.model
    def _is_so_manager(self):
        return self.env.user.has_group(MANAGER_GROUP)

    def _check_role(self, role, states):
        """Validate the current user may run a workflow step; workflow writes then run with sudo."""
        self.check_access('write')
        manager = self._is_so_manager()
        for request in self:
            if request.state not in states:
                raise UserError(_('This action is not available for %(name)s in status "%(state)s".',
                                  name=request.name, state=dict(STATES)[request.state]))
            if role == 'requester' and not (manager or request.requesting_user_id == self.env.user):
                raise AccessError(_('Only the requesting dentist can do this on %s.', request.name))
            if role == 'specialist' and request.specialist_user_id != self.env.user:
                raise AccessError(_('Only the assigned specialist can do this on %s.', request.name))

    def _log_event(self, event, note=False, state_from=False):
        self.ensure_one()
        self.env['dental.second.opinion.log'].sudo().create({
            'request_id': self.id,
            'event': event,
            'user_id': self.env.user.id,
            'state_from': state_from or False,
            'state_to': self.state,
            'note': note or False,
        })

    def _transition(self, state, event, note=False, extra_vals=None):
        self.ensure_one()
        state_from = self.state
        self.sudo().write(dict(extra_vals or {}, state=state))
        self._log_event(event, note=note, state_from=state_from)

    def _notify_user(self, user, subject, body):
        """Post a chatter message that notifies ``user`` (inbox or email, per their preference)."""
        self.ensure_one()
        if user and user.partner_id:
            self.sudo().message_post(
                body=body, subject=subject, partner_ids=user.partner_id.ids,
                message_type='comment', subtype_xmlid='mail.mt_comment')

    def _set_activity(self, user, summary, note=False):
        """Close the open workflow to-dos of this request and, if given, assign the next one to ``user``."""
        self.ensure_one()
        request = self.sudo()
        request.activity_unlink([ACTIVITY_TYPE])
        if user:
            request.activity_schedule(
                ACTIVITY_TYPE, user_id=user.id, summary=summary, note=note or '',
                date_deadline=self.due_date or fields.Date.context_today(self))

    @staticmethod
    def _quote(text):
        return Markup('<br/>').join((text or '').splitlines())

    # ------------------------------------------------------------------------------------------
    # Workflow: requesting dentist
    # ------------------------------------------------------------------------------------------

    def action_submit(self):
        self._check_role('requester', ('draft',))
        for request in self:
            if not request.specialist_id:
                raise UserError(_('Choose the specialist who should review %s.', request.name))
            if not (request.clinical_question or '').strip():
                raise UserError(_('Describe the clinical question for the specialist.'))
            request._transition('submitted', 'submitted', extra_vals={'submitted_date': fields.Datetime.now()})
            specialist = request.specialist_user_id
            request.sudo().message_subscribe(partner_ids=specialist.partner_id.ids)
            request._set_activity(specialist, _('Review second opinion %s', request.name), request.clinical_question)
            request._notify_user(specialist, _('Second opinion requested: %s', request.name), Markup(
                '<p>%s</p><p><b>%s</b><br/>%s</p>') % (
                _('%(dentist)s requests your second opinion on case %(case)s (patient %(patient)s).',
                  dentist=request.requesting_doctor_id.name or request.requesting_user_id.name,
                  case=request.case_id.name, patient=request.patient_id.name),
                _('Clinical question'), self._quote(request.clinical_question)))
        return True

    def action_provide_info(self, note):
        """Answer the specialist's request for information and hand the case back for review."""
        self._check_role('requester', ('info_requested',))
        for request in self:
            request._transition('in_review', 'info_provided', note=note)
            request._set_activity(request.specialist_user_id, _('Continue review of %s', request.name), note)
            request._notify_user(request.specialist_user_id, _('Information provided: %s', request.name),
                                 Markup('<p>%s</p><p>%s</p>') % (_('The requesting dentist answered:'), self._quote(note)))
        return True

    def action_request_clarification(self, note):
        self._check_role('requester', ('opinion_submitted',))
        for request in self:
            request._transition('clarification', 'clarification_requested', note=note,
                                extra_vals={'clarification_note': note})
            request._set_activity(request.specialist_user_id, _('Clarify opinion %s', request.name), note)
            request._notify_user(request.specialist_user_id, _('Clarification requested: %s', request.name),
                                 Markup('<p>%s</p><p>%s</p>') % (_('The requesting dentist asks for clarification:'), self._quote(note)))
        return True

    def action_record_decision(self, decision, note):
        """Record the final clinical decision. Treatment plans are deliberately left untouched."""
        self._check_role('requester', ('opinion_submitted',))
        if decision not in dict(DECISIONS):
            raise UserError(_('Choose a clinical decision.'))
        now = fields.Datetime.now()
        for request in self:
            request._transition('closed', 'decision_recorded', note=_('%(decision)s\n%(note)s', decision=dict(DECISIONS)[decision], note=note or ''), extra_vals={
                'decision': decision, 'decision_notes': note, 'decided_by_id': self.env.user.id,
                'decision_date': now, 'closed_date': now,
            })
            request._set_activity(False, False)
            request._notify_user(request.specialist_user_id, _('Decision recorded: %s', request.name), Markup(
                '<p>%s</p><p><b>%s</b></p><p>%s</p>') % (
                _('The requesting dentist recorded the final clinical decision:'), dict(DECISIONS)[decision], self._quote(note)))
        return True

    def action_cancel(self):
        self._check_role('requester', ('draft', 'declined') + OPEN_STATES)
        for request in self:
            notify = request.specialist_user_id if request.state in OPEN_STATES else False
            request._transition('cancelled', 'cancelled', extra_vals={'closed_date': fields.Datetime.now()})
            request._set_activity(False, False)
            if notify:
                request._notify_user(notify, _('Second opinion cancelled: %s', request.name),
                                     _('The requesting dentist cancelled this second opinion request.'))
        return True

    def action_reset_to_draft(self):
        """Reopen a declined or cancelled request, e.g. to choose another specialist."""
        self._check_role('requester', ('declined', 'cancelled'))
        for request in self:
            # Clearing the sent date hides the draft from the previous specialist until it is sent again
            request._transition('draft', 'reset_to_draft', extra_vals={
                'closed_date': False, 'submitted_date': False, 'review_start_date': False})
            if request.specialist_user_id:
                request.sudo().message_unsubscribe(partner_ids=request.specialist_user_id.partner_id.ids)
        return True

    # ------------------------------------------------------------------------------------------
    # Workflow: specialist
    # ------------------------------------------------------------------------------------------

    def action_start_review(self):
        self._check_role('specialist', ('submitted',))
        for request in self:
            request._transition('in_review', 'review_started', extra_vals={'review_start_date': fields.Datetime.now()})
            request._notify_user(request.requesting_user_id, _('Review started: %s', request.name),
                                 _('%s started reviewing this case.', request.specialist_id.name))
        return True

    def action_request_info(self, note):
        self._check_role('specialist', ('in_review',))
        for request in self:
            request._transition('info_requested', 'info_requested', note=note, extra_vals={'info_request_note': note})
            request._set_activity(request.requesting_user_id, _('Provide information for %s', request.name), note)
            request._notify_user(request.requesting_user_id, _('Information requested: %s', request.name),
                                 Markup('<p>%s</p><p>%s</p>') % (_('The specialist needs more information:'), self._quote(note)))
        return True

    def action_decline(self, note):
        self._check_role('specialist', ('submitted', 'in_review'))
        for request in self:
            request._transition('declined', 'declined', note=note, extra_vals={'decline_reason': note})
            request._set_activity(request.requesting_user_id, _('Reassign second opinion %s', request.name), note)
            request._notify_user(request.requesting_user_id, _('Second opinion declined: %s', request.name),
                                 Markup('<p>%s</p><p>%s</p>') % (_('The specialist declined this request:'), self._quote(note)))
        return True

    def action_submit_opinion(self):
        self._check_role('specialist', self._OPINION_EDIT_STATES)
        for request in self:
            if not request.recommended_action or not _has_text(request.findings) or not _has_text(request.recommendations):
                raise UserError(_('Enter the findings, recommendations and recommended action before submitting.'))
            revision = request.opinion_revision + 1
            event = 'opinion_submitted' if revision == 1 else 'opinion_revised'
            vals = {'opinion_revision': revision, 'opinion_date': request.opinion_date or fields.Datetime.now()}
            # Snapshot of each submitted revision, so later edits never erase what the dentist relied on
            snapshot = _('Revision %(rev)s - %(action)s\n\nFindings:\n%(findings)s\n\nRecommendations:\n%(recs)s',
                         rev=revision, action=dict(RECOMMENDED_ACTIONS)[request.recommended_action],
                         findings=_plain(request.findings), recs=_plain(request.recommendations))
            request._transition('opinion_submitted', event, note=snapshot, extra_vals=vals)
            request._set_activity(request.requesting_user_id, _('Record clinical decision for %s', request.name))
            request._notify_user(request.requesting_user_id, _('Second opinion received: %s', request.name), Markup(
                '<p>%s</p><p><b>%s</b> %s</p><p>%s</p>') % (
                _('%s submitted an opinion. Record your clinical decision or request clarification.', request.specialist_id.name),
                _('Recommended action:'), dict(RECOMMENDED_ACTIONS)[request.recommended_action], _('Open the request to read the findings and recommendations.')))
        return True

    # ------------------------------------------------------------------------------------------
    # Wizards and navigation
    # ------------------------------------------------------------------------------------------

    def _open_wizard(self, action, title):
        self.ensure_one()
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'dental.second.opinion.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id, 'default_action': action},
        }

    def action_open_request_info(self):
        return self._open_wizard('request_info', _('Request Information'))

    def action_open_provide_info(self):
        return self._open_wizard('provide_info', _('Provide Information'))

    def action_open_decline(self):
        return self._open_wizard('decline', _('Decline Request'))

    def action_open_clarification(self):
        return self._open_wizard('clarification', _('Request Clarification'))

    def action_open_decision(self):
        return self._open_wizard('decision', _('Record Clinical Decision'))

    def action_open_treatment_plan(self):
        """Open the referenced plan in the clinical workflow; the dentist edits it there, by hand."""
        self.ensure_one()
        if not self.treatment_plan_id:
            raise UserError(_('No treatment plan is linked to this request.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'dental.treatment.plan',
            'res_id': self.treatment_plan_id.id,
            'view_mode': 'form',
            'target': 'current',
        }


def _plain(html):
    return html2plaintext(html or '').strip()


def _has_text(html):
    return bool(_plain(html))
