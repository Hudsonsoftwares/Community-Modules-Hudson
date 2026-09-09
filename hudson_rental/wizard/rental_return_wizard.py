# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class RentalReturnWizard(models.TransientModel):
    _name = 'rental.return.wizard'
    _description = 'Rental Return Wizard'

    order_id = fields.Many2one('rental.order', string='Rental Order', required=True)
    return_date = fields.Datetime(string='Return Date', required=True, default=fields.Datetime.now)
    expected_return_date = fields.Datetime(related='order_id.return_date', readonly=True)
    partner_id = fields.Many2one(related='order_id.partner_id', readonly=True)
    is_late = fields.Boolean(string='Late Return', compute='_compute_is_late')
    late_days = fields.Float(string='Days Late', compute='_compute_is_late')
    late_fee = fields.Float(string='Late Fee', compute='_compute_is_late')
    note = fields.Text(string='Notes')
    line_ids = fields.One2many('rental.return.line', 'wizard_id', string='Lines')
    create_invoice = fields.Boolean(string='Create Invoice', default=True)

    @api.depends('return_date', 'expected_return_date')
    def _compute_is_late(self):
        for wizard in self:
            if wizard.return_date and wizard.expected_return_date:
                if wizard.return_date > wizard.expected_return_date:
                    delta = wizard.return_date - wizard.expected_return_date
                    wizard.is_late = True
                    wizard.late_days = delta.days + (delta.seconds / 86400.0)
                    # Calculate late fees
                    total_fee = 0.0
                    for line in wizard.order_id.order_line_ids:
                        if line.product_id.late_fee_per_day:
                            total_fee += wizard.late_days * line.product_id.late_fee_per_day * line.quantity
                    wizard.late_fee = total_fee
                else:
                    wizard.is_late = False
                    wizard.late_days = 0.0
                    wizard.late_fee = 0.0
            else:
                wizard.is_late = False
                wizard.late_days = 0.0
                wizard.late_fee = 0.0

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
                    'returned_quantity': line.quantity,
                    'condition': 'good',
                }))
            res['line_ids'] = lines
        return res

    def action_confirm_return(self):
        self.ensure_one()
        
        if self.order_id.state != 'picked_up':
            raise UserError(_('Order must be in picked up state'))
        
        # Update order and lines
        self.order_id.write({
            'state': 'returned',
            'actual_return_date': self.return_date,
        })
        
        for line in self.order_id.order_line_ids:
            line.actual_return_date = self.return_date
        
        # Create return picking if needed
        self._create_return_picking()
        
        # Create invoice if requested
        if self.create_invoice:
            self.order_id.action_create_invoice()
        
        return {'type': 'ir.actions.act_window_close'}

    def _create_return_picking(self):
        """Create stock picking for returned items"""
        if not self.order_id.company_id.rental_location_id:
            return
        
        StockPicking = self.env['stock.picking']
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'incoming'),
            ('warehouse_id.company_id', '=', self.order_id.company_id.id)
        ], limit=1)
        
        picking_vals = {
            'partner_id': self.order_id.partner_id.id,
            'origin': self.order_id.name,
            'rental_order_id': self.order_id.id,
            'picking_type_id': picking_type.id,
            'location_id': self.order_id.partner_id.property_stock_customer.id,
            'location_dest_id': self.order_id.company_id.rental_location_id.id,
            'scheduled_date': self.return_date,
        }
        picking = StockPicking.create(picking_vals)
        
        # Create moves
        for line in self.line_ids:
            is_storable = getattr(line.product_id, 'is_storable', line.product_id.type == 'product')
            if is_storable and line.returned_quantity > 0:
                self.env['stock.move'].create({
                    'name': line.product_id.name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.returned_quantity,
                    'product_uom': line.product_id.uom_id.id,
                    'picking_id': picking.id,
                    'location_id': self.order_id.partner_id.property_stock_customer.id,
                    'location_dest_id': self.order_id.company_id.rental_location_id.id,
                })
        
        # Validate picking
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            if hasattr(move, 'quantity_done'):
                move.quantity_done = move.product_uom_qty
            if hasattr(move, 'quantity'):
                move.quantity = move.product_uom_qty
            if hasattr(move, 'picked'):
                move.picked = True
        picking.button_validate()


class RentalReturnLine(models.TransientModel):
    _name = 'rental.return.line'
    _description = 'Rental Return Line'

    wizard_id = fields.Many2one('rental.return.wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    quantity = fields.Float(string='Rented Quantity', required=True)
    returned_quantity = fields.Float(string='Returned Quantity', required=True)
    condition = fields.Selection([
        ('good', 'Good'),
        ('damaged', 'Damaged'),
        ('lost', 'Lost'),
    ], string='Condition', required=True, default='good')
    notes = fields.Text(string='Notes')
