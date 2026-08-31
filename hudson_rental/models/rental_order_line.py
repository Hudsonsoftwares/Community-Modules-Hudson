# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import timedelta


class RentalOrderLine(models.Model):
    _name = 'rental.order.line'
    _description = 'Rental Order Line'
    _order = 'order_id, sequence, id'

    sequence = fields.Integer(string='Sequence', default=10)
    order_id = fields.Many2one('rental.order', string='Order Reference', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True,
                                  domain="[('is_rental', '=', True)]")
    name = fields.Text(string='Description', required=True)
    quantity = fields.Float(string='Quantity', required=True, default=1.0, digits='Product Unit of Measure')
    product_uom = fields.Many2one('uom.uom', string='Unit of Measure', required=True)
    
    pickup_date = fields.Datetime(string='Pickup Date', related='order_id.pickup_date', store=True)
    return_date = fields.Datetime(string='Expected Return', related='order_id.return_date', store=True)
    actual_return_date = fields.Datetime(string='Actual Return', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Customer', related='order_id.partner_id', store=True)
    
    duration_days = fields.Float(string='Duration (Days)', compute='_compute_duration', store=True)
    duration_hours = fields.Float(string='Duration (Hours)', compute='_compute_duration', store=True)
    
    price_unit = fields.Float(string='Unit Price', required=True, digits='Product Price')
    price_subtotal = fields.Monetary(string='Subtotal', compute='_compute_amount', store=True)
    price_tax = fields.Float(string='Tax', compute='_compute_amount', store=True)
    price_total = fields.Monetary(string='Total', compute='_compute_amount', store=True)
    
    tax_id = fields.Many2many('account.tax', string='Taxes',
                               domain="[('type_tax_use', '=', 'sale')]")
    
    deposit_amount = fields.Float(string='Security Deposit', compute='_compute_deposit', store=True)
    late_fee = fields.Float(string='Late Fee', compute='_compute_late_fee', store=True)
    late_days = fields.Float(string='Days Late', compute='_compute_late_fee', store=True)
    
    rental_status = fields.Selection([
        ('draft', 'Draft'),
        ('reserved', 'Reserved'),
        ('picked_up', 'Picked Up'),
        ('returned', 'Returned'),
        ('done', 'Done'),
    ], string='Status', default='draft', compute='_compute_rental_status', store=True)
    
    currency_id = fields.Many2one(related='order_id.currency_id', store=True, readonly=True)
    company_id = fields.Many2one(related='order_id.company_id', store=True, readonly=True)
    
    qty_invoiced = fields.Float(string='Invoiced Quantity', default=0.0, readonly=True)

    @api.depends('order_id.state')
    def _compute_rental_status(self):
        for line in self:
            if line.order_id.state in ['draft', 'confirmed']:
                line.rental_status = 'draft'
            elif line.order_id.state == 'reserved':
                line.rental_status = 'reserved'
            elif line.order_id.state == 'picked_up':
                line.rental_status = 'picked_up'
            elif line.order_id.state in ['returned', 'done']:
                line.rental_status = 'returned'
            else:
                line.rental_status = 'done'

    @api.depends('pickup_date', 'return_date')
    def _compute_duration(self):
        for line in self:
            if line.pickup_date and line.return_date:
                delta = line.return_date - line.pickup_date
                line.duration_hours = delta.total_seconds() / 3600.0
                line.duration_days = delta.days + (delta.seconds / 86400.0)
            else:
                line.duration_hours = 0.0
                line.duration_days = 0.0

    @api.depends('quantity', 'price_unit', 'tax_id')
    def _compute_amount(self):
        for line in self:
            price = line.price_unit * line.quantity
            taxes = line.tax_id.compute_all(
                price,
                currency=line.currency_id,
                quantity=1.0,
                product=line.product_id,
                partner=line.order_id.partner_id
            )
            line.update({
                'price_subtotal': taxes['total_excluded'],
                'price_tax': taxes['total_included'] - taxes['total_excluded'],
                'price_total': taxes['total_included'],
            })

    @api.depends('product_id', 'quantity')
    def _compute_deposit(self):
        for line in self:
            if line.product_id and line.product_id.security_deposit:
                line.deposit_amount = line.product_id.security_deposit * line.quantity
            else:
                line.deposit_amount = 0.0

    @api.depends('actual_return_date', 'return_date', 'product_id', 'quantity')
    def _compute_late_fee(self):
        for line in self:
            if line.actual_return_date and line.return_date:
                if line.actual_return_date > line.return_date:
                    delta = line.actual_return_date - line.return_date
                    late_days = delta.days + (delta.seconds / 86400.0)
                    line.late_days = late_days
                    
                    if line.product_id.late_fee_per_day:
                        line.late_fee = late_days * line.product_id.late_fee_per_day * line.quantity
                    else:
                        line.late_fee = 0.0
                else:
                    line.late_days = 0.0
                    line.late_fee = 0.0
            else:
                line.late_days = 0.0
                line.late_fee = 0.0

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.get_product_multiline_description_sale()
            self.product_uom = self.product_id.uom_id
            
            # Set default tax
            self.tax_id = self.product_id.taxes_id

    @api.onchange('product_id', 'duration_days', 'quantity')
    def _onchange_price_unit(self):
        if self.product_id and self.duration_days > 0:
            # Calculate price based on duration
            self.price_unit = self.product_id.product_tmpl_id.get_rental_price(
                self.duration_days, 'day'
            )

    @api.constrains('quantity')
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_('Quantity must be positive'))

    def get_rental_duration_display(self):
        self.ensure_one()
        if self.duration_days < 1:
            return f"{round(self.duration_hours, 1)} hours"
        elif self.duration_days == 1:
            return "1 day"
        else:
            return f"{round(self.duration_days, 1)} days"
