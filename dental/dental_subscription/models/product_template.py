from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

DENTAL_SUBSCRIPTION_TYPES = [
    ('membership', 'Dental Membership'),
    ('family', 'Family Membership'),
    ('preventive', 'Preventive Care Package'),
    ('installment', 'Orthodontic Installment Plan'),
    ('maintenance', 'Post-Treatment Maintenance'),
]


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    dental_membership_type = fields.Selection(
        DENTAL_SUBSCRIPTION_TYPES, string='Dental Subscription Type',
        help='Makes this subscription product a dental membership/package. '
             'Only available on subscription (recurring) products.')
    dental_max_members = fields.Integer(
        string='Covered Members', default=1,
        help='Maximum number of patients one subscription of this product covers '
             '(the subscriber included). Family memberships need at least 2.')
    dental_benefit_rule_ids = fields.One2many(
        'dental.membership.benefit.rule', 'product_tmpl_id', string='Membership Benefits', copy=True)

    @api.constrains('dental_membership_type', 'recurring_invoice', 'dental_max_members')
    def _check_dental_membership(self):
        for template in self.filtered('dental_membership_type'):
            if not template.recurring_invoice:
                raise ValidationError(_(
                    "%s: a dental subscription type can only be set on a Subscription Product.", template.name))
            if template.dental_max_members < 1:
                raise ValidationError(_("%s must cover at least one member.", template.name))
            if template.dental_membership_type == 'family' and template.dental_max_members < 2:
                raise ValidationError(_("%s: a family membership must cover at least 2 members.", template.name))
            if template.dental_membership_type == 'installment' and template.dental_max_members != 1:
                raise ValidationError(_("%s: an orthodontic installment plan covers exactly one patient.", template.name))

    @api.onchange('dental_membership_type')
    def _onchange_dental_membership_type(self):
        if self.dental_membership_type:
            self.recurring_invoice = True
            self.type = 'service'
            if self.dental_membership_type == 'family' and self.dental_max_members < 2:
                self.dental_max_members = 4
            elif self.dental_membership_type != 'family':
                self.dental_max_members = 1
