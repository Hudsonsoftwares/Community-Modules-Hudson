# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from datetime import timezone
from zoneinfo import ZoneInfo

from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rental_location_id = fields.Many2one(
        'stock.location',
        string='Rental Location',
        related='company_id.rental_location_id',
        readonly=False,
        help='Location where rental products are stored'
    )
    rental_picking_type_id = fields.Many2one(
        'stock.picking.type',
        string='Rental Picking Type',
        related='company_id.rental_picking_type_id',
        readonly=False,
        help='Picking type for rental deliveries'
    )
    rental_calendar_id = fields.Many2one(
        'resource.calendar',
        string='Availabilities',
        related='company_id.rental_calendar_id',
        readonly=False,
        help='Days during which pickup and return are possible.'
    )
    rental_use_transfers = fields.Boolean(
        string='Rental Transfers',
        related='company_id.rental_use_transfers',
        readonly=False,
        help="Activate to use stock deliveries and receipts for rental orders."
    )
    # Quotation templates ship with sale_management, which this module depends on
    module_sale_management = fields.Boolean(string='Quotation Templates')


class Company(models.Model):
    _inherit = 'res.company'

    rental_location_id = fields.Many2one('stock.location', string='Rental Location')
    rental_picking_type_id = fields.Many2one('stock.picking.type', string='Rental Picking Type')
    rental_deposit_product_id = fields.Many2one('product.product', string='Deposit Product')
    rental_auto_invoice = fields.Boolean(string='Auto Create Invoice', default=False)
    rental_require_deposit = fields.Boolean(string='Require Security Deposit', default=True)
    rental_calendar_id = fields.Many2one(
        'resource.calendar', string='Rental Availabilities',
        help='Days during which pickup and return are possible. Leave empty to allow every day.')
    rental_use_transfers = fields.Boolean(string='Rental Transfers', default=False)
    rental_out_location_id = fields.Many2one(
        'stock.location', string='Rented Out Location',
        help='Internal location holding the picked-up rented products until their return. It is '
             'outside the warehouses, so these units are not counted in the On Hand quantity.')

    def _get_rental_warehouse(self):
        self.ensure_one()
        return self.env['stock.warehouse'].search([('company_id', '=', self.id)], limit=1)

    def _get_rental_location(self):
        """Stock location rented products leave from and come back to."""
        self.ensure_one()
        return self.rental_location_id or self._get_rental_warehouse().lot_stock_id

    def _get_rental_out_location(self):
        """Location of the units out with customers, like the "Rental" location of Odoo's
        Rental app: an internal location outside every warehouse, created on first use."""
        self.ensure_one()
        location = self.rental_out_location_id
        if not location:
            location = self.env['stock.location'].sudo().create({
                'name': self.env._('Rental'),
                'usage': 'internal',
                'company_id': self.id,
            })
            self.sudo().rental_out_location_id = location
        return location

    def _get_rental_picking_type(self, code='outgoing'):
        self.ensure_one()
        if code == 'outgoing' and self.rental_picking_type_id:
            return self.rental_picking_type_id
        warehouse = self._get_rental_warehouse()
        return warehouse.out_type_id if code == 'outgoing' else warehouse.in_type_id

    def _get_rental_delay_product(self):
        """Service product of the "Late return" lines added on late returns."""
        product = self.env.ref('hudson_rental.product_late_fee', raise_if_not_found=False)
        if not product:
            # Recreated if it was deleted
            product = self.env['product.product'].sudo().create({
                'name': self.env._('Late Return Fee'), 'type': 'service', 'invoice_policy': 'order',
                'sale_ok': False, 'purchase_ok': False, 'list_price': 0.0,
            })
            self.env['ir.model.data'].sudo().create({
                'module': 'hudson_rental', 'name': 'product_late_fee', 'noupdate': True,
                'model': 'product.product', 'res_id': product.id,
            })
        return product

    def _is_rental_day_available(self, dt):
        """Whether pickups/returns are possible at ``dt`` (naive UTC) per the availabilities."""
        self.ensure_one()
        calendar = self.rental_calendar_id
        if not calendar or not dt:
            return True
        tz_name = self.partner_id.tz or self.env.user.tz or 'UTC'
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
        local_date = dt.replace(tzinfo=timezone.utc).astimezone(tz).date()
        return calendar._works_on_date(local_date)
