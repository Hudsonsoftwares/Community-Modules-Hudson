# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class RentalPickupWizard(models.TransientModel):
    _name = 'rental.pickup.wizard'
    _description = 'Rental Pickup Wizard'

    order_id = fields.Many2one('rental.order', string='Rental Order', required=True)
    pickup_date = fields.Datetime(string='Pickup Date', required=True, default=fields.Datetime.now)
    partner_id = fields.Many2one(related='order_id.partner_id', readonly=True)
    note = fields.Text(string='Notes')
    line_ids = fields.One2many('rental.pickup.line', 'wizard_id', string='Lines')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'order_id' in res and res['order_id']:
            order = self.env['rental.order'].browse(res['order_id'])
            lines = []
            for line in order.order_line_ids:
                lines.append((0, 0, {
                    'product_id': line.product_id.id,
                    'quantity': line.quantity,
                    'picked_quantity': line.quantity,
                }))
            res['line_ids'] = lines
        return res

    def action_confirm_pickup(self):
        self.ensure_one()
        
        if self.order_id.state != 'reserved':
            raise UserError(_('Order must be in reserved state'))
        
        # Update order state
        self.order_id.write({
            'state': 'picked_up',
            'pickup_date': self.pickup_date,
        })
        
        # Validate pickings if any
        for picking in self.order_id.picking_ids.filtered(lambda p: p.state not in ['done', 'cancel']):
            picking.action_assign()
            for move in picking.move_ids:
                if hasattr(move, 'quantity_done'):
                    move.quantity_done = move.product_uom_qty
                if hasattr(move, 'quantity'):
                    move.quantity = move.product_uom_qty
                if hasattr(move, 'picked'):
                    move.picked = True
            picking.button_validate()
        
        return {'type': 'ir.actions.act_window_close'}


class RentalPickupLine(models.TransientModel):
    _name = 'rental.pickup.line'
    _description = 'Rental Pickup Line'

    wizard_id = fields.Many2one('rental.pickup.wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    quantity = fields.Float(string='Expected Quantity', required=True)
    picked_quantity = fields.Float(string='Picked Quantity', required=True)
