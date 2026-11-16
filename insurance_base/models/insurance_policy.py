from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain

POLICY_STATUS = [
    ('valid', 'Valid'),
    ('not_started', 'Not Started'),
    ('expired', 'Expired'),
    ('inactive', 'Inactive'),
]


class InsurancePolicy(models.Model):
    """A patient's membership in an insurance plan (what is on the card)."""
    _name = 'insurance.policy'
    _description = 'Patient Insurance Policy'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'partner_id, priority, id'

    name = fields.Char(compute='_compute_name', store=True)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, index=True)
    partner_id = fields.Many2one('res.partner', string='Patient', required=True, index=True,
                                 ondelete='cascade', tracking=True)
    holder_id = fields.Many2one('res.partner', string='Policyholder', tracking=True,
                                help='Person who owns the policy (the patient, or e.g. a parent).')
    relationship = fields.Selection([
        ('self', 'Self'),
        ('spouse', 'Spouse'),
        ('child', 'Child'),
        ('parent', 'Parent'),
        ('other', 'Other'),
    ], string='Relationship to Holder', default='self', required=True)
    priority = fields.Integer(default=1, help='1 = primary policy, 2 = secondary...')

    plan_id = fields.Many2one('insurance.plan', string='Plan', index=True, tracking=True)
    insurer_id = fields.Many2one(
        'res.partner', string='Insurance Company', compute='_compute_from_plan', store=True, precompute=True,
        readonly=False, required=True, index=True, tracking=True,
        domain=[('insurance_partner_type', '=', 'insurer')])
    tpa_id = fields.Many2one(
        'res.partner', string='TPA', compute='_compute_from_plan', store=True, precompute=True, readonly=False,
        tracking=True, domain=[('insurance_partner_type', '=', 'tpa')])
    payer_id = fields.Many2one('res.partner', string='Payer', compute='_compute_payer',
                               help='Who answers eligibility checks and claims: the TPA if any, '
                                    'else the insurance company.')
    connector = fields.Selection(related='payer_id.insurance_connector', string='Connector')

    member_id = fields.Char(string='Member ID', required=True, tracking=True,
                            help='Member / card number of the patient.')
    policy_number = fields.Char(tracking=True)
    group_number = fields.Char(help='Corporate / group policy number, if any.')
    date_start = fields.Date(string='Valid From', tracking=True)
    date_end = fields.Date(string='Valid Until', tracking=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id,
                                  required=True)
    sum_insured = fields.Monetary(tracking=True)
    status = fields.Selection(POLICY_STATUS, compute='_compute_status', search='_search_status')

    card_front = fields.Binary(string='Card (front)', attachment=True)
    card_front_filename = fields.Char()
    card_back = fields.Binary(string='Card (back)', attachment=True)
    card_back_filename = fields.Char()
    note = fields.Text(string='Notes')

    eligibility_ids = fields.One2many('insurance.eligibility', 'policy_id', string='Eligibility Checks')
    eligibility_count = fields.Integer(compute='_compute_eligibility')
    last_eligibility_id = fields.Many2one('insurance.eligibility', string='Last Check',
                                          compute='_compute_eligibility')
    last_verified_date = fields.Datetime(string='Last Verified', readonly=True, copy=False)
    eligibility_status = fields.Selection([
        ('eligible', 'Eligible'),
        ('not_eligible', 'Not Eligible'),
    ], string='Eligibility', readonly=True, copy=False, tracking=True,
        help='Result of the last completed eligibility check.')

    _member_uniq = models.Constraint(
        'UNIQUE(insurer_id, member_id, partner_id)',
        'This patient already has a policy with this member ID at this insurer.')

    @api.depends('insurer_id.name', 'member_id', 'plan_id.name')
    def _compute_name(self):
        for policy in self:
            parts = [policy.insurer_id.name, policy.plan_id.name, policy.member_id]
            policy.name = ' / '.join(p for p in parts if p)

    @api.depends('plan_id')
    def _compute_from_plan(self):
        for policy in self:
            if policy.plan_id:
                policy.insurer_id = policy.plan_id.insurer_id
                if policy.plan_id.tpa_id or not policy.tpa_id:
                    policy.tpa_id = policy.plan_id.tpa_id
            elif not policy.insurer_id:
                policy.insurer_id = False

    @api.depends('insurer_id', 'tpa_id')
    def _compute_payer(self):
        for policy in self:
            policy.payer_id = policy.tpa_id or policy.insurer_id

    @api.depends('active', 'date_start', 'date_end')
    def _compute_status(self):
        today = fields.Date.context_today(self)
        for policy in self:
            if not policy.active:
                policy.status = 'inactive'
            elif policy.date_start and policy.date_start > today:
                policy.status = 'not_started'
            elif policy.date_end and policy.date_end < today:
                policy.status = 'expired'
            else:
                policy.status = 'valid'

    def _search_status(self, operator, value):
        if operator not in ('in', 'not in'):
            return NotImplemented
        today = fields.Date.context_today(self)
        by_status = {
            'inactive': Domain('active', '=', False),
            'not_started': Domain('active', '=', True) & Domain('date_start', '>', today),
            'expired': (Domain('active', '=', True)
                        & (Domain('date_start', '=', False) | Domain('date_start', '<=', today))
                        & Domain('date_end', '<', today)),
            'valid': (Domain('active', '=', True)
                      & (Domain('date_start', '=', False) | Domain('date_start', '<=', today))
                      & (Domain('date_end', '=', False) | Domain('date_end', '>=', today))),
        }
        domain = Domain.OR(by_status[v] for v in value if v in by_status)
        return ~domain if operator == 'not in' else domain

    @api.depends('eligibility_ids')
    def _compute_eligibility(self):
        for policy in self:
            checks = policy.eligibility_ids.sorted('id', reverse=True)
            policy.eligibility_count = len(checks)
            policy.last_eligibility_id = checks[:1]

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for policy in self:
            if policy.date_start and policy.date_end and policy.date_end < policy.date_start:
                raise UserError(self.env._("The policy ends before it starts."))

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------
    def _new_eligibility_vals(self, **overrides):
        self.ensure_one()
        vals = {
            'policy_id': self.id,
            'company_id': self.company_id.id or self.env.company.id,
            'service_date': fields.Date.context_today(self),
        }
        vals.update(overrides)
        return vals

    def action_check_eligibility(self):
        """Create an eligibility check and send it through the payer's connector.

        Manual payers: the check opens so staff can record what the payer said.
        Connected payers: the request is sent at once; the answer arrives later.
        """
        self.ensure_one()
        check = self.env['insurance.eligibility'].create(self._new_eligibility_vals())
        if check.connector != 'manual':
            check.action_send()
        return check._get_form_action()

    def action_view_eligibility(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('insurance_base.action_insurance_eligibility')
        action.update({'domain': [('policy_id', '=', self.id)],
                       'context': {'default_policy_id': self.id}})
        return action
