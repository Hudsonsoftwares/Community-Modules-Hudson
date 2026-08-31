# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api


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
    rental_late_fee_product_id = fields.Many2one(
        'product.product',
        string='Late Fee Product',
        related='company_id.rental_late_fee_product_id',
        readonly=False,
        help='Product used for late fee invoicing'
    )
    rental_deposit_product_id = fields.Many2one(
        'product.product',
        string='Deposit Product',
        related='company_id.rental_deposit_product_id',
        readonly=False,
        help='Product used for security deposit'
    )
    rental_auto_invoice = fields.Boolean(
        string='Auto Create Invoice',
        related='company_id.rental_auto_invoice',
        readonly=False,
        help='Automatically create invoice when rental is returned'
    )
    rental_require_deposit = fields.Boolean(
        string='Require Security Deposit',
        related='company_id.rental_require_deposit',
        readonly=False,
        help='Require security deposit for all rentals'
    )
    rental_unavailability_monday = fields.Boolean(string="Monday", related='company_id.rental_unavailability_monday', readonly=False)
    rental_unavailability_tuesday = fields.Boolean(string="Tuesday", related='company_id.rental_unavailability_tuesday', readonly=False)
    rental_unavailability_wednesday = fields.Boolean(string="Wednesday", related='company_id.rental_unavailability_wednesday', readonly=False)
    rental_unavailability_thursday = fields.Boolean(string="Thursday", related='company_id.rental_unavailability_thursday', readonly=False)
    rental_unavailability_friday = fields.Boolean(string="Friday", related='company_id.rental_unavailability_friday', readonly=False)
    rental_unavailability_saturday = fields.Boolean(string="Saturday", related='company_id.rental_unavailability_saturday', readonly=False)
    rental_unavailability_sunday = fields.Boolean(string="Sunday", related='company_id.rental_unavailability_sunday', readonly=False)
    rental_use_transfers = fields.Boolean(
        string='Rental Transfers',
        related='company_id.rental_use_transfers',
        readonly=False,
        help="Activate to use stock deliveries and receipts for rental orders."
    )


class Company(models.Model):
    _inherit = 'res.company'

    rental_location_id = fields.Many2one('stock.location', string='Rental Location')
    rental_picking_type_id = fields.Many2one('stock.picking.type', string='Rental Picking Type')
    rental_late_fee_product_id = fields.Many2one('product.product', string='Late Fee Product')
    rental_deposit_product_id = fields.Many2one('product.product', string='Deposit Product')
    rental_auto_invoice = fields.Boolean(string='Auto Create Invoice', default=False)
    rental_require_deposit = fields.Boolean(string='Require Security Deposit', default=True)
    
    rental_unavailability_monday = fields.Boolean(string="Monday", default=False)
    rental_unavailability_tuesday = fields.Boolean(string="Tuesday", default=False)
    rental_unavailability_wednesday = fields.Boolean(string="Wednesday", default=False)
    rental_unavailability_thursday = fields.Boolean(string="Thursday", default=False)
    rental_unavailability_friday = fields.Boolean(string="Friday", default=False)
    rental_unavailability_saturday = fields.Boolean(string="Saturday", default=False)
    rental_unavailability_sunday = fields.Boolean(string="Sunday", default=False)
    rental_use_transfers = fields.Boolean(string='Rental Transfers', default=True)
