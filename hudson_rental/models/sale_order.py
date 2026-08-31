# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    is_rental_order = fields.Boolean(string='Is Rental Order', default=False)
    rental_order_id = fields.Many2one('rental.order', string='Rental Order', readonly=True)
    rental_start_date = fields.Datetime(string='Rental Start')
    rental_end_date = fields.Datetime(string='Rental End')
    has_rental_product = fields.Boolean(string="Has Rental Product", compute="_compute_has_rental_product", store=True)

    @api.depends('order_line.is_rental')
    def _compute_has_rental_product(self):
        for order in self:
            order.has_rental_product = any(line.is_rental for line in order.order_line)

    @api.onchange('rental_start_date', 'rental_end_date')
    def _onchange_rental_dates(self):
        for line in self.order_line.filtered(lambda l: l.is_rental):
            line.rental_start_date = self.rental_start_date
            line.rental_end_date = self.rental_end_date
            line._compute_rental_duration()
            line._onchange_rental_price()

    def action_view_rental_order(self):
        self.ensure_one()
        return {
            'name': 'Rental Order',
            'type': 'ir.actions.act_window',
            'res_model': 'rental.order',
            'view_mode': 'form',
            'res_id': self.rental_order_id.id,
        }


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    is_rental = fields.Boolean(string='Is Rental', related='product_id.is_rental', store=True)
    rental_start_date = fields.Datetime(string='Rental Start')
    rental_end_date = fields.Datetime(string='Rental End')
    rental_duration = fields.Float(string='Duration (Days)', compute='_compute_rental_duration', store=True)

    @api.depends('rental_start_date', 'rental_end_date')
    def _compute_rental_duration(self):
        for line in self:
            if line.rental_start_date and line.rental_end_date:
                delta = line.rental_end_date - line.rental_start_date
                line.rental_duration = delta.days + (delta.seconds / 86400.0)
            else:
                line.rental_duration = 0.0

    @api.onchange('product_id', 'rental_duration', 'rental_start_date', 'rental_end_date')
    def _onchange_rental_price(self):
        # Auto-fill dates from header if not set
        if self.is_rental and self.order_id and not self.rental_start_date:
            self.rental_start_date = self.order_id.rental_start_date
            self.rental_end_date = self.order_id.rental_end_date
            self._compute_rental_duration()
        
        if self.is_rental and self.rental_duration > 0:
            price = self.product_id.product_tmpl_id.get_rental_price(self.rental_duration, 'day')
            if price:
                self.price_unit = price

    def _action_launch_stock_rule(self, previous_product_uom_qty=False):
        # Skip standard stock procurement for rental lines so they don't appear in the delivery order
        lines_to_launch = self.filtered(lambda l: not l.is_rental)
        return super(SaleOrderLine, lines_to_launch)._action_launch_stock_rule(previous_product_uom_qty=previous_product_uom_qty)
