# -*- coding: utf-8 -*-
from odoo import api, models


def _default_available_in_pos(vals_list):
    # A new medicine can be sold at the pharmacy counter unless stated otherwise
    for vals in vals_list:
        if vals.get('is_medicine') and 'available_in_pos' not in vals:
            vals['available_in_pos'] = True


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model_create_multi
    def create(self, vals_list):
        _default_available_in_pos(vals_list)
        return super().create(vals_list)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model_create_multi
    def create(self, vals_list):
        _default_available_in_pos(vals_list)
        return super().create(vals_list)
