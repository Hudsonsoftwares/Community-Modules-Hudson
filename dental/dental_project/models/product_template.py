from odoo import api, models

# Dental treatments are billed per step as its visits are done (delivered quantity, set by the
# treatment plan), and never create tasks of their own: the plan already has one task per step.
DENTAL_TREATMENT_SALE_VALUES = {
    'invoice_policy': 'delivery',
    'service_type': 'manual',
    'service_tracking': 'no',
}


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model
    def _dental_set_delivery_invoicing(self):
        treatments = self.with_context(active_test=False).search([
            ('is_dental_treatment', '=', True), ('type', '=', 'service')])
        for field_name, value in DENTAL_TREATMENT_SALE_VALUES.items():
            treatments.filtered(lambda p: p[field_name] != value).write({field_name: value})
        return treatments

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('is_dental_treatment') and vals.get('type', 'service') == 'service':
                for field_name, value in DENTAL_TREATMENT_SALE_VALUES.items():
                    vals.setdefault(field_name, value)
        return super().create(vals_list)
