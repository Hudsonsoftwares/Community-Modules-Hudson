# -*- coding: utf-8 -*-
from odoo import models

class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    def _get_applicable_rules_domain(self, products, date, **kwargs):
        domain = super()._get_applicable_rules_domain(products, date, **kwargs)
        plan_id = self.env.context.get('subscription_plan_id')
        if plan_id:
            domain.append(('subscription_plan_id', '=', plan_id))
        else:
            domain.append(('subscription_plan_id', '=', False))
            
        packaging_id = self.env.context.get('product_packaging_id')
        if packaging_id:
            domain.append(('packaging_id', 'in', (packaging_id, False)))
        else:
            domain.append(('packaging_id', '=', False))
            
        return domain
