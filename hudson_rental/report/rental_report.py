# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, tools


class RentalReport(models.Model):
    _name = 'rental.report'
    _description = 'Rental Analysis Report'
    _auto = False
    _order = 'date_order desc'

    name = fields.Char(string='Order Reference', readonly=True)
    date_order = fields.Datetime(string='Order Date', readonly=True)
    pickup_date = fields.Datetime(string='Pickup Date', readonly=True)
    return_date = fields.Datetime(string='Return Date', readonly=True)
    state = fields.Selection([
        ('draft', 'Quotation'),
        ('confirmed', 'Confirmed'),
        ('reserved', 'Reserved'),
        ('picked_up', 'In Progress'),
        ('returned', 'Returned'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], string='Status', readonly=True)
    
    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    product_tmpl_id = fields.Many2one('product.template', string='Product Template', readonly=True)
    categ_id = fields.Many2one('product.category', string='Product Category', readonly=True)
    
    quantity = fields.Float(string='Quantity', readonly=True)
    duration_days = fields.Float(string='Duration (Days)', readonly=True)
    
    price_total = fields.Float(string='Total', readonly=True)
    amount_untaxed = fields.Float(string='Untaxed Amount', readonly=True)
    amount_late_fee = fields.Float(string='Late Fees', readonly=True)
    
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    user_id = fields.Many2one('res.users', string='Salesperson', readonly=True)
    
    invoice_status = fields.Selection([
        ('no', 'Nothing to Invoice'),
        ('to_invoice', 'To Invoice'),
        ('invoiced', 'Fully Invoiced'),
    ], string='Invoice Status', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    rol.id as id,
                    ro.name as name,
                    ro.date_order as date_order,
                    ro.pickup_date as pickup_date,
                    ro.return_date as return_date,
                    ro.state as state,
                    ro.partner_id as partner_id,
                    ro.user_id as user_id,
                    ro.company_id as company_id,
                    ro.invoice_status as invoice_status,
                    ro.amount_late_fee as amount_late_fee,
                    rol.product_id as product_id,
                    pt.id as product_tmpl_id,
                    pt.categ_id as categ_id,
                    rol.quantity as quantity,
                    rol.duration_days as duration_days,
                    rol.price_total as price_total,
                    rol.price_subtotal as amount_untaxed
                FROM rental_order_line rol
                JOIN rental_order ro ON ro.id = rol.order_id
                JOIN product_product pp ON pp.id = rol.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
            )
        """ % self._table)
