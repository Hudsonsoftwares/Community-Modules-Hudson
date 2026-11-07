# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

import math
from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import ValidationError

# Length of each rental period unit, in days
RENTAL_PERIOD_DAYS = {
    'hour': 1.0 / 24.0,
    'day': 1.0,
    'week': 7.0,
    'month': 30.0,
}


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Like Odoo's Rental app, a product is rentable as soon as it has a periodicity:
    # leaving it blank means "Not for Rent".
    rental_periodicity = fields.Selection([
        ('hour', 'Hours'),
        ('day', 'Days'),
        ('week', 'Weeks'),
        ('month', 'Months'),
    ], string='Periodicity',
        help='Rental period the sales price applies to. Leave empty if the product is not for rent.')
    rental_period_label = fields.Char(compute='_compute_rental_period_label')

    rental_pickup_time = fields.Float(
        string='Pickup',
        default=8.0,
        help="Earliest time of the day the product can be picked up or returned (website)."
    )

    rental_return_time = fields.Float(
        string='Return',
        default=18.0,
        help="Latest time of the day the product can be picked up or returned (website)."
    )
    # Hourly rentals have no fixed pickup/return times: instead, each booking keeps the
    # product unavailable for this many hours before its pickup (cleaning, preparation...)
    rental_padding_time = fields.Float(
        string='Padding Time',
        digits=(16, 2),
        help='Temporarily make this product unavailable before pickup.',
    )

    is_rental = fields.Boolean(
        string='Can be Rented',
        compute='_compute_is_rental',
        store=True,
        help='A product can be rented when a rental periodicity is set'
    )
    rent_ok = fields.Boolean(
        string='Rentable',
        related='is_rental',
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
        string='Rental Stock Available',
        compute='_compute_rental_stock_available'
    )
    rental_order_count = fields.Integer(
        string='Rental Orders',
        compute='_compute_rental_order_count'
    )
    qty_in_rent = fields.Float(
        string='In Rental',
        compute='_compute_qty_in_rent',
        digits='Product Unit',
    )
    security_deposit = fields.Float(
        string='Security Deposit',
        help='Refundable security deposit amount'
    )

    @api.depends('rental_periodicity')
    def _compute_is_rental(self):
        for product in self:
            product.is_rental = bool(product.rental_periodicity)

    @api.depends('rental_periodicity')
    def _compute_rental_period_label(self):
        labels = {'hour': self.env._('Hour'), 'day': self.env._('Day'),
                  'week': self.env._('Week'), 'month': self.env._('Month')}
        for product in self:
            product.rental_period_label = labels.get(product.rental_periodicity, '')

    @api.constrains('rental_padding_time', 'rental_pickup_time', 'rental_return_time')
    def _check_rental_times(self):
        for product in self:
            if product.rental_padding_time < 0:
                raise ValidationError(self.env._('The padding time cannot be negative.'))
            for time_ in (product.rental_pickup_time, product.rental_return_time):
                if not 0 <= time_ < 24:
                    raise ValidationError(self.env._('Pickup and return times must be between 00:00 and 23:59.'))

    def _get_rental_padding(self):
        """Time the product stays unavailable before each pickup (hourly rentals only)."""
        self.ensure_one()
        if self.rental_periodicity != 'hour':
            return timedelta()
        return timedelta(hours=max(self.rental_padding_time, 0.0))

    def _get_rental_time_window(self):
        """Allowed pickup/return times on the website as (first, last) minutes after
        midnight: from the product's Pickup time to its Return time (it spans midnight when
        the Return time comes first). None when any time is allowed (hourly rentals)."""
        self.ensure_one()
        if self.rental_periodicity == 'hour' or not self.rental_periodicity:
            return None
        return round(self.rental_pickup_time * 60) % 1440, round(self.rental_return_time * 60) % 1440

    def _is_rental_time_allowed(self, minutes):
        window = self._get_rental_time_window()
        if window is None:
            return True
        first, last = window
        if first <= last:
            return first <= minutes <= last
        return minutes >= first or minutes <= last

    def get_rental_time_options(self):
        """Times offered on the website rental period, as (minutes after midnight, label):
        every hour for hourly rentals, else the product's Pickup time, each full hour after
        it, and its Return time."""
        self.ensure_one()
        window = self._get_rental_time_window()
        if window is None:
            minutes = [hour * 60 for hour in range(24)]
        else:
            first, last = window
            span = (last - first) % 1440
            # Full hours strictly inside the window, then both bounds
            steps = [first + offset for offset in range(60 - first % 60 or 60, span, 60)]
            minutes = [first] + [m % 1440 for m in steps] + ([last] if last != first else [])
        return [(m, self._format_rental_time(m)) for m in minutes]

    def _format_rental_time(self, minutes):
        return '%d:%02d%s' % ((minutes // 60) % 12 or 12, minutes % 60, 'am' if minutes < 720 else 'pm')

    @api.depends('is_rental', 'rental_pricing_ids')
    def _compute_rental_ok(self):
        for product in self:
            product.rental_ok = bool(product.is_rental)

    def _rental_lines(self, domain=()):
        """Rental lines of confirmed orders for these products."""
        return self.env['sale.order.line'].search([
            ('product_id', 'in', self.product_variant_ids.ids),
            ('is_rental', '=', True),
            ('state', '=', 'sale'),
            *domain,
        ])

    def _compute_rental_stock_available(self):
        for product in self:
            # On-hand quantity (picked-up units already left it) minus what is reserved and
            # still to pick up
            lines = product._rental_lines()
            rented = sum(lines.mapped('product_uom_qty')) - sum(lines.mapped('qty_delivered'))
            available_qty = sum(product.product_variant_ids.mapped('qty_available'))
            product.rental_stock_available = max(0.0, available_qty - rented)

    def _compute_rental_order_count(self):
        for product in self:
            product.rental_order_count = len(product._rental_lines().order_id)

    def _compute_qty_in_rent(self):
        for product in self:
            lines = product._rental_lines()
            product.qty_in_rent = sum(lines.mapped('qty_delivered')) - sum(lines.mapped('qty_returned'))

    def action_view_rental_orders(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('hudson_rental.action_rental_order')
        action['domain'] = [('order_line.product_id', 'in', self.product_variant_ids.ids)]
        return action

    def _get_rental_period_count(self, duration_days):
        """Number of started periods of the product's periodicity in ``duration_days``."""
        self.ensure_one()
        if duration_days <= 0:
            return 0
        period_days = RENTAL_PERIOD_DAYS[self.rental_periodicity or 'day']
        return max(1, math.ceil(round(duration_days / period_days, 6)))

    def _get_rental_period_label(self, count, extra=False):
        """e.g. "3 Days", or "1 extra Day" with ``extra``."""
        self.ensure_one()
        _ = self.env._
        singular, plural = {
            'hour': (_('Hour'), _('Hours')), 'day': (_('Day'), _('Days')),
            'week': (_('Week'), _('Weeks')), 'month': (_('Month'), _('Months')),
        }[self.rental_periodicity or 'day']
        unit = singular if count == 1 else plural
        return _('%(count)s extra %(unit)s', count=count, unit=unit) if extra else f"{count} {unit}"

    def get_rental_price(self, duration, duration_unit='day'):
        """Return the rental price of one unit for the given duration.

        Every started period is charged. The cheapest of the pricing rules is used;
        without rules, the sales price is charged per period of the product's periodicity.
        """
        self.ensure_one()
        duration_days = duration * RENTAL_PERIOD_DAYS.get(duration_unit, 1.0)
        if duration_days <= 0:
            return 0.0

        def periods(period_days):
            # round() avoids charging an extra period for float noise (e.g. 7.0000001 days)
            return max(1, math.ceil(round(duration_days / period_days, 6)))

        prices = [
            periods(pricing.duration * RENTAL_PERIOD_DAYS[pricing.duration_unit]) * pricing.price
            for pricing in self.rental_pricing_ids
            if pricing.duration > 0
        ]
        if not prices and self.rental_periodicity:
            prices.append(periods(RENTAL_PERIOD_DAYS[self.rental_periodicity]) * self.list_price)
        return min(prices) if prices else 0.0


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _get_rental_available_qty(self, start, end, company, exclude_lines=None):
        """Units of the product free between ``start`` and ``end`` (naive UTC): the stock
        minus what other confirmed rentals overlapping the period hold."""
        self.ensure_one()
        location = company._get_rental_location()
        on_hand = self.with_context(location=location.id).qty_available if location else self.qty_available
        others = self.env['sale.order.line'].search([
            ('product_id', '=', self.id),
            ('is_rental', '=', True),
            ('state', '=', 'sale'),
            ('id', 'not in', (exclude_lines or self.env['sale.order.line']).ids),
        ])
        # Each booking holds the product from its pickup minus the padding time (hourly
        # rentals) until its return: two bookings clash when these spans overlap.
        padding = self.product_tmpl_id._get_rental_padding()
        start = start - padding
        overlapping = others.filtered(
            lambda l: l.rental_start_date and l.rental_end_date
            and l.rental_start_date - padding < end and l.rental_end_date > start)
        # Picked-up units already left the stock (to the customer with Rental Transfers, else
        # to the Rental location): only bookings still to pick up are missing, and units out
        # on earlier rentals come back before this one starts.
        back_before = others.filtered(lambda l: l.rental_end_date and l.rental_end_date <= start)
        return (on_hand
                + sum(l.qty_delivered - l.qty_returned for l in back_before)
                - sum(l.product_uom_qty - l.qty_delivered for l in overlapping))

    def _get_rental_unavailable_message(self, qty, available, uom=None):
        """Message for a rental of ``qty`` units when only ``available`` are free, else False."""
        self.ensure_one()
        if qty <= available:
            return False
        if available <= 0:
            return self.env._('%s is not available for the selected period. Please choose other dates.',
                              self.display_name)
        qty_label = int(available) if float(available).is_integer() else available
        if available == 1:
            return self.env._('Only 1 %(product)s is available for the selected period.',
                              product=self.display_name)
        return self.env._(
            'Only %(qty)s %(uom)s of %(product)s are available for the selected period.',
            qty=qty_label, uom=(uom or self.uom_id).name.lower(), product=self.display_name)
