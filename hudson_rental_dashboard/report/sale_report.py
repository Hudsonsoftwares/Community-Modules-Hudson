# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class SaleReport(models.Model):
    _inherit = 'sale.report'

    # Per line, so the rental dashboard only counts the rented products of an order
    is_rental = fields.Boolean(string='Is Rental', readonly=True)

    def _select_dict(self, table):
        return super()._select_dict(table) | {'is_rental': table.is_rental}

    def _groupby_list(self, table):
        return super()._groupby_list(table) + [table.is_rental]
