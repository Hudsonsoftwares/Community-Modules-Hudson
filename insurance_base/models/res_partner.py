from odoo import api, fields, models

INSURANCE_USER = 'insurance_base.group_insurance_user'


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # --- payer side (insurance companies, TPAs) -------------------------
    insurance_partner_type = fields.Selection([
        ('insurer', 'Insurance Company'),
        ('tpa', 'TPA (Third-Party Administrator)'),
    ], string='Insurance Role', index=True,
        help='Set on companies that pay for treatment: an insurer, or the TPA that '
             'processes its claims.')
    insurance_connector = fields.Selection(
        [('manual', 'Manual (phone / payer portal)')],
        string='Connector', default='manual',
        help='How eligibility checks and claims reach this payer. Manual: staff '
             'contact the payer and record the answer. Connectors such as NHCX send '
             'them electronically.')

    # --- patient side ----------------------------------------------------
    insurance_policy_ids = fields.One2many(
        'insurance.policy', 'partner_id', string='Insurance Policies', groups=INSURANCE_USER)
    insurance_policy_count = fields.Integer(
        compute='_compute_insurance_policy_count', groups=INSURANCE_USER)
    has_valid_insurance = fields.Boolean(
        string='Insured', compute='_compute_has_valid_insurance', groups=INSURANCE_USER,
        help='At least one active policy valid today.')

    @api.depends('insurance_policy_ids')
    def _compute_insurance_policy_count(self):
        for partner in self:
            partner.insurance_policy_count = len(partner.insurance_policy_ids)

    @api.depends('insurance_policy_ids.status')
    def _compute_has_valid_insurance(self):
        for partner in self:
            partner.has_valid_insurance = any(
                p.status == 'valid' for p in partner.insurance_policy_ids)

    def action_view_insurance_policies(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('insurance_base.action_insurance_policy')
        action.update({
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id, 'default_holder_id': self.id},
        })
        return action
