from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.model
    def _dental_create_or_extend_invoice(self, partner, company, line_vals, case=False, origin=False):
        """Every visit/case invoice of the clinic goes through here: apply membership benefits once."""
        line_vals = self.env['sale.order']._dental_apply_membership_benefits(partner, company, line_vals)
        return super()._dental_create_or_extend_invoice(partner, company, line_vals, case=case, origin=origin)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    # The usage record of a membership benefit; cancelling the invoice releases the use
    dental_subscription_benefit_id = fields.Many2one(
        'dental.subscription.benefit', string='Membership Benefit', index='btree_not_null',
        copy=False, readonly=True, check_company=True, ondelete='restrict')
    dental_subscription_id = fields.Many2one(
        related='dental_subscription_benefit_id.order_id', string='Membership', store=True, index='btree_not_null')
