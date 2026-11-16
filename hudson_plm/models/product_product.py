# -*- coding: utf-8 -*-
from odoo import models


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def action_view_ecos(self):
        # The variant form is built from the template form, so the template's
        # ECO smart button also appears here and needs a method on this model.
        self.ensure_one()
        return self.product_tmpl_id.action_view_ecos()
