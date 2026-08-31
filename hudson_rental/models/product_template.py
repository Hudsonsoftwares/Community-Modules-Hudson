# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    rental_periodicity = fields.Selection([
        ('hour', 'Hours'),
        ('day', 'Days'),
        ('week', 'Weeks'),
        ('month', 'Months'),
    ], string='Periodicity')
    
    rental_pickup_time = fields.Float(
        string='Pickup', 
        default=14.0
    )
    
    rental_return_time = fields.Float(
        string='Return', 
        default=10.0
    )

    is_rental = fields.Boolean(
        string='Can be Rented',
        compute='_compute_is_rental',
        store=True,
        help='Computed automatically based on periodicity'
    )
    rental_pricing_ids = fields.One2many(
        'rental.pricing',
        'product_tmpl_id',
        string='Rental Pricing'
    )
    rental_ok = fields.Boolean(
        string='Available for Rent',
        compute='_compute_rental_ok',
        store=True
    )
    min_rental_duration = fields.Float(
        string='Minimum Rental Duration (Days)',
        default=1.0,
        help='Minimum rental period required'
    )
    max_rental_duration = fields.Float(
        string='Maximum Rental Duration (Days)',
        default=365.0,
        help='Maximum rental period allowed'
    )
    rental_stock_available = fields.Float(
        string='Available for Rent',
        compute='_compute_rental_stock_available'
    )
    rental_order_count = fields.Integer(
        string='Rental Orders',
        compute='_compute_rental_order_count'
    )
    late_fee_per_day = fields.Float(
        string='Late Fee Per Day',
        help='Additional fee charged per day if product is returned late'
    )
    security_deposit = fields.Float(
        string='Security Deposit',
        help='Refundable security deposit amount'
    )

    @api.depends('is_rental', 'rental_pricing_ids')
    def _compute_rental_ok(self):
        for product in self:
            product.rental_ok = product.is_rental and len(product.rental_pricing_ids) > 0

    @api.depends('rental_periodicity')
    def _compute_is_rental(self):
        for product in self:
            product.is_rental = bool(product.rental_periodicity)

    def _compute_rental_stock_available(self):
        for product in self:
            # Calculate available rental stock (on-hand - currently rented)
            rented_qty = self.env['rental.order.line'].search([
                ('product_id', 'in', product.product_variant_ids.ids),
                ('rental_status', 'in', ['reserved', 'picked_up'])
            ])
            total_rented = sum(rented_qty.mapped('quantity'))
            
            available_qty = sum(product.product_variant_ids.mapped('qty_available'))
            product.rental_stock_available = max(0, available_qty - total_rented)

    def _compute_rental_order_count(self):
        for product in self:
            product.rental_order_count = self.env['rental.order.line'].search_count([
                ('product_id', 'in', product.product_variant_ids.ids)
            ])

    def action_view_rental_orders(self):
        self.ensure_one()
        return {
            'name': 'Rental Orders',
            'type': 'ir.actions.act_window',
            'res_model': 'rental.order',
            'view_mode': 'tree,form',
            'domain': [('order_line_ids.product_id', 'in', self.product_variant_ids.ids)],
            'context': {'default_product_id': self.product_variant_id.id}
        }

    def get_rental_price(self, duration, duration_unit='day'):
        """Calculate rental price based on duration"""
        self.ensure_one()
        
        # Convert duration to days
        duration_days = duration
        if duration_unit == 'hour':
            duration_days = duration / 24.0
        elif duration_unit == 'week':
            duration_days = duration * 7.0
        elif duration_unit == 'month':
            duration_days = duration * 30.0
        
        # Find applicable pricing
        pricing = self.rental_pricing_ids.filtered(
            lambda p: p.duration_unit == duration_unit and p.duration == duration
        )
        
        if pricing:
            return pricing[0].price
        
        # Calculate based on daily rate if specific pricing not found
        daily_pricing = self.rental_pricing_ids.filtered(lambda p: p.duration_unit == 'day' and p.duration == 1)
        if daily_pricing:
            return daily_pricing[0].price * duration_days
        
        return 0.0
