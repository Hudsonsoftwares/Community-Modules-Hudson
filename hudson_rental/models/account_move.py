# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api


class AccountMove(models.Model):
    _inherit = 'account.move'

    rental_order_id = fields.Many2one('rental.order', string='Rental Order', readonly=True)
    is_rental_invoice = fields.Boolean(string='Is Rental Invoice', compute='_compute_is_rental', store=True)

    @api.depends('rental_order_id')
    def _compute_is_rental(self):
        for invoice in self:
            invoice.is_rental_invoice = bool(invoice.rental_order_id)
