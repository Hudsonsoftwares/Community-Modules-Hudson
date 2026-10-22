# -*- coding: utf-8 -*-
# pyrefly: ignore [missing-import]
from odoo import api, fields, models


class ApprovalProductLine(models.Model):
    _name = 'approval.product.line'
    _description = 'Approval Product Line'

    request_id = fields.Many2one(
        'approval.request', string='Approval Request',
        required=True, ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', string='Product', required=True)
    product_uom_id = fields.Many2one(
        'uom.uom', string='Unit of Measure')
    quantity = fields.Float(string='Quantity', default=1.0)
    description = fields.Char(string='Description')
    price_unit = fields.Float(string='Unit Price')
    amount = fields.Monetary(
        string='Amount', compute='_compute_amount', store=True)
    currency_id = fields.Many2one(
        'res.currency', related='request_id.currency_id', store=True)

    @api.depends('quantity', 'price_unit')
    def _compute_amount(self):
        for line in self:
            line.amount = line.quantity * line.price_unit

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id
            self.price_unit = self.product_id.standard_price
            if not self.description:
                self.description = self.product_id.display_name
