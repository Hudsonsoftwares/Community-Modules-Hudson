from odoo import api, fields, models
from odoo.exceptions import UserError


class InsuranceEligibility(models.Model):
    """One eligibility / benefits check of a policy with its payer.

    Connectors implement ``_send_<connector>()`` to send the request, then call
    ``_apply_result()`` (or ``_set_error()``) when the payer answers. The
    manual connector has nothing to send: staff record the payer's answer.
    """
    _name = 'insurance.eligibility'
    _description = 'Insurance Eligibility Check'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='/')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, index=True)
    policy_id = fields.Many2one('insurance.policy', required=True, index=True, ondelete='cascade')
    partner_id = fields.Many2one(related='policy_id.partner_id', string='Patient', store=True,
                                 index=True)
    insurer_id = fields.Many2one(related='policy_id.insurer_id', store=True)
    payer_id = fields.Many2one('res.partner', string='Payer', compute='_compute_payer',
                               store=True, readonly=True,
                               help='Payer the request was addressed to (TPA or insurance company).')
    connector = fields.Selection(selection='_selection_connector', compute='_compute_payer',
                                 store=True, readonly=True)
    purpose = fields.Selection([
        ('validation', 'Policy in force?'),
        ('benefits', 'Benefits & balances'),
        ('discovery', 'Find coverage'),
    ], default='benefits', required=True)
    service_date = fields.Date(default=fields.Date.context_today, required=True,
                               help='Date of the planned treatment.')
    product_tmpl_ids = fields.Many2many('product.template', string='Planned Services',
                                        help='Optional: ask the payer about these services only.')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting', 'Waiting for Payer'),
        ('done', 'Answered'),
        ('error', 'Error'),
        ('cancel', 'Cancelled'),
    ], default='draft', required=True, tracking=True, index=True)
    result = fields.Selection([
        ('eligible', 'Eligible'),
        ('not_eligible', 'Not Eligible'),
    ], tracking=True, readonly=True)
    request_date = fields.Datetime(readonly=True, copy=False)
    response_date = fields.Datetime(readonly=True, copy=False)
    external_ref = fields.Char(string='Request ID', readonly=True, copy=False, index=True,
                               help="Connector's reference of the request (e.g. NHCX correlation ID).")
    payer_reference = fields.Char(readonly=True, copy=False, help="Payer's reference of the answer.")
    disposition = fields.Text(string='Payer Message', help="Payer's free-text answer.")
    benefit_start = fields.Date(string='Benefit Period From')
    benefit_end = fields.Date(string='Benefit Period To')
    currency_id = fields.Many2one(related='policy_id.currency_id')
    benefit_line_ids = fields.One2many('insurance.eligibility.benefit', 'eligibility_id',
                                       string='Benefits')
    error_message = fields.Text(readonly=True, copy=False)
    response_data = fields.Json(readonly=True, copy=False, groups='base.group_system',
                                help='Raw answer of the payer, for troubleshooting.')

    @api.model
    def _selection_connector(self):
        return self.env['res.partner']._fields['insurance_connector']._description_selection(self.env)

    @api.depends('policy_id')
    def _compute_payer(self):
        for check in self:
            payer = check.policy_id.payer_id
            check.payer_id = payer
            check.connector = payer.insurance_connector or 'manual'

    @api.model_create_multi
    def create(self, vals_list):
        checks = super().create(vals_list)
        for check in checks:
            if check.name in (False, '/'):
                check.name = 'ELG/%05d' % check.id
        return checks

    def _get_form_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------
    def action_send(self):
        for check in self:
            if check.state not in ('draft', 'error'):
                raise UserError(self.env._("%s was already sent.", check.name))
            if check.policy_id.status != 'valid':
                check.message_post(body=self.env._(
                    "Warning: the policy is %s on the card dates.",
                    dict(check.policy_id._fields['status']._description_selection(self.env))
                    .get(check.policy_id.status)))
            method = getattr(check, '_send_%s' % check.connector, None)
            if not method:
                raise UserError(self.env._(
                    "No connector is installed for %(payer)s (%(connector)s).",
                    payer=check.payer_id.display_name, connector=check.connector))
            check.write({'error_message': False, 'request_date': fields.Datetime.now()})
            method()
        return True

    def _send_manual(self):
        """Nothing to send: staff contact the payer and record the answer."""
        self.write({'state': 'waiting'})

    # ------------------------------------------------------------------
    # Answer
    # ------------------------------------------------------------------
    def _apply_result(self, result, benefits=None, **vals):
        """Store the payer's answer.

        :param result: 'eligible' or 'not_eligible'
        :param benefits: list of dicts for ``insurance.eligibility.benefit``
        :param vals: other fields (disposition, benefit_start, payer_reference...)
        """
        self.ensure_one()
        now = fields.Datetime.now()
        write_vals = dict(vals, state='done', result=result, response_date=now, error_message=False)
        if benefits is not None:
            write_vals['benefit_line_ids'] = [fields.Command.clear()] + [
                fields.Command.create(b) for b in benefits]
        self.write(write_vals)
        self.policy_id.write({'last_verified_date': now, 'eligibility_status': result})
        label = dict(self._fields['result']._description_selection(self.env))[result]
        self.policy_id.message_post(body=self.env._(
            "Eligibility check %(ref)s: %(result)s", ref=self.name, result=label))
        return True

    def _set_error(self, message):
        self.write({'state': 'error', 'error_message': str(message)[:5000],
                    'response_date': fields.Datetime.now()})

    def action_mark_eligible(self):
        for check in self:
            check._apply_result('eligible')
        return True

    def action_mark_not_eligible(self):
        for check in self:
            check._apply_result('not_eligible')
        return True

    def action_cancel(self):
        self.write({'state': 'cancel'})
        return True

    def action_reset_draft(self):
        self.filtered(lambda c: c.state in ('error', 'cancel')).write({'state': 'draft'})
        return True

    def action_check_again(self):
        """New check for the same policy (an answered check is never changed)."""
        self.ensure_one()
        return self.policy_id.action_check_eligibility()


class InsuranceEligibilityBenefit(models.Model):
    _name = 'insurance.eligibility.benefit'
    _description = 'Eligibility Benefit Line'
    _order = 'eligibility_id, sequence, id'

    sequence = fields.Integer(default=10)
    eligibility_id = fields.Many2one('insurance.eligibility', required=True, index=True,
                                     ondelete='cascade')
    currency_id = fields.Many2one(related='eligibility_id.currency_id')
    name = fields.Char(string='Benefit', required=True)
    category = fields.Char(help='Benefit category, e.g. Dental care, OPD, Hospitalization.')
    service = fields.Char(help='Service or product the line is about, if any.')
    benefit_type = fields.Char(string='Type', help='e.g. benefit, deductible, co-pay, visits.')
    network = fields.Selection([('in', 'In network'), ('out', 'Out of network')])
    term = fields.Char(help='e.g. annual, per visit, lifetime.')
    covered = fields.Boolean(default=True)
    requires_preauth = fields.Boolean(string='Pre-Auth Required')
    allowed_amount = fields.Monetary(string='Allowed')
    used_amount = fields.Monetary(string='Used')
    remaining_amount = fields.Monetary(string='Remaining', compute='_compute_remaining', store=True)
    allowed_value = fields.Char(string='Allowed (other)', help='Non-money limits, e.g. 2 visits, 80 %.')
    used_value = fields.Char(string='Used (other)')
    description = fields.Text()

    @api.depends('allowed_amount', 'used_amount')
    def _compute_remaining(self):
        for line in self:
            line.remaining_amount = (max(line.allowed_amount - line.used_amount, 0.0)
                                     if line.allowed_amount else 0.0)
