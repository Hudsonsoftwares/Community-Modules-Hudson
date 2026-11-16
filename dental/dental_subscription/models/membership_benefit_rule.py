from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

BENEFIT_TYPES = [
    ('covered', 'Fully Covered'),
    ('discount', 'Discount'),
]
LIMIT_PERIODS = [
    ('billing', 'Per Billing Period'),
    ('year', 'Per Contract Year'),
    ('term', 'Whole Subscription'),
]


class DentalBenefitMixin(models.AbstractModel):
    """Fields shared by benefit rules (catalog) and benefit entitlements (per subscription)."""
    _name = 'dental.benefit.mixin'
    _description = 'Dental Membership Benefit Definition'

    sequence = fields.Integer(default=10)
    name = fields.Char(string='Benefit', required=True)
    treatment_id = fields.Many2one(
        'product.template', string='Treatment', index=True,
        domain=[('is_dental_treatment', '=', True)],
        help='Treatment this benefit applies to. Leave empty to use the category, '
             'or both empty to apply to every dental treatment and consultation.')
    treatment_category_id = fields.Many2one('dental.treatment.category', string='Treatment Category')
    benefit_type = fields.Selection(BENEFIT_TYPES, string='Benefit Type', required=True, default='discount')
    discount = fields.Float(string='Discount (%)', digits='Discount')
    quantity_limit = fields.Integer(
        string='Uses Allowed', default=0,
        help='How many times the benefit can be used in the limit period. 0 means unlimited.')
    limit_period = fields.Selection(LIMIT_PERIODS, string='Limit Period', required=True, default='year')

    @api.constrains('benefit_type', 'discount', 'quantity_limit')
    def _check_benefit_values(self):
        for record in self:
            if record.benefit_type == 'discount' and not (0 < record.discount <= 100):
                raise ValidationError(_("Benefit '%s': the discount must be between 0 and 100%%.", record.name))
            if record.quantity_limit < 0:
                raise ValidationError(_("Benefit '%s': uses allowed cannot be negative.", record.name))

    @api.onchange('treatment_id', 'treatment_category_id', 'benefit_type', 'discount')
    def _onchange_benefit_name(self):
        if self.name:
            return
        target = self.treatment_id.name or self.treatment_category_id.name or _('All treatments')
        if self.benefit_type == 'covered':
            self.name = _('%s – covered', target)
        elif self.discount:
            self.name = _('%(target)s – %(discount)s%% off', target=target, discount=round(self.discount, 2))

    def _get_discount(self):
        self.ensure_one()
        return 100.0 if self.benefit_type == 'covered' else self.discount

    def _matches_product(self, template):
        """Whether this benefit applies to the billed product template."""
        self.ensure_one()
        if self.treatment_id:
            return self.treatment_id == template
        if self.treatment_category_id:
            return template.dental_treatment_category_id == self.treatment_category_id
        return bool(template.is_dental_treatment)


class DentalMembershipBenefitRule(models.Model):
    """Benefit template defined on a membership product (Treatment Catalog side)."""
    _name = 'dental.membership.benefit.rule'
    _inherit = ['dental.benefit.mixin']
    _description = 'Membership Benefit Rule'
    _order = 'product_tmpl_id, sequence, id'
    _check_company_auto = True

    product_tmpl_id = fields.Many2one(
        'product.template', string='Membership Product', required=True, ondelete='cascade', index=True)
    # Optionally shared, like the catalog product it belongs to (dental_base/SECURITY.md)
    company_id = fields.Many2one(related='product_tmpl_id.company_id', store=True, index=True)

    def _prepare_subscription_benefit_vals(self, order):
        self.ensure_one()
        return {
            'order_id': order.id,
            'rule_id': self.id,
            'sequence': self.sequence,
            'name': self.name,
            'treatment_id': self.treatment_id.id,
            'treatment_category_id': self.treatment_category_id.id,
            'benefit_type': self.benefit_type,
            'discount': self.discount,
            'quantity_limit': self.quantity_limit,
            'limit_period': self.limit_period,
        }
