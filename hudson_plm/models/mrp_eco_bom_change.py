# -*- coding: utf-8 -*-
from odoo import models, fields, api

class MrpEcoBomChange(models.Model):
    _name = 'mrp.eco.bom.change'
    _description = 'ECO BoM Changes'
    _order = 'change_type, product_id'

    eco_id = fields.Many2one('mrp.eco', string='ECO', required=True, ondelete='cascade')
    change_type = fields.Selection([
        ('add', 'Add'),
        ('remove', 'Remove'),
        ('update', 'Update')
    ], string='Type', required=True)
    
    product_id = fields.Many2one('product.product', string='Components', required=True)
    uom_id = fields.Many2one('uom.uom', related='product_id.uom_id', string='Unit of Measure')
    
    old_qty = fields.Float('Old Quantity', default=0.0)
    new_qty = fields.Float('New Quantity', default=0.0)
    
    quantity_diff = fields.Float('Quantity', compute='_compute_diffs', store=True)
    cost_diff = fields.Monetary('BoM Cost', compute='_compute_diffs', store=True, currency_field='currency_id')
    
    currency_id = fields.Many2one('res.currency', related='eco_id.company_id.currency_id')

    @api.depends('new_qty', 'old_qty', 'product_id', 'product_id.standard_price')
    def _compute_diffs(self):
        for record in self:
            record.quantity_diff = record.new_qty - record.old_qty
            record.cost_diff = record.quantity_diff * record.product_id.standard_price
