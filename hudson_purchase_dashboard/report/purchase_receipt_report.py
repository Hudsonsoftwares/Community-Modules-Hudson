# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import fields, models, tools


class PurchaseReceiptReport(models.Model):
    """ Done receipts of purchase orders compared to the planned dates of their order lines, for the on-time
    deliveries and late receipts of the Purchase dashboard (fields of Odoo Enterprise only).
    """
    _name = 'purchase.receipt.report'
    _description = 'Purchase Receipt Analysis'
    _auto = False
    _order = 'date_done desc'

    name = fields.Char(string='Picking Name', readonly=True)
    picking_id = fields.Many2one('stock.picking', string='Receipt', readonly=True)
    order_id = fields.Many2one('purchase.order', string='Order', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Vendor', readonly=True)
    user_id = fields.Many2one('res.users', string='Buyer', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    date_planned = fields.Datetime(string='Expected Arrival', readonly=True)
    date_done = fields.Datetime(string='Date of Transfer', readonly=True)
    delay = fields.Float(string='Delay (Days)', digits=(16, 2), readonly=True, aggregator='avg')
    on_time_rate = fields.Float(string='On-Time Delivery Rate', digits=(16, 2), readonly=True, aggregator='avg',
                                help="100 for a receipt done by the expected arrival date of its order lines, else 0: "
                                     "its average is the percentage of receipts on time.")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    MIN(move.id) AS id,
                    picking.name AS name,
                    picking.id AS picking_id,
                    po.id AS order_id,
                    po.partner_id AS partner_id,
                    po.user_id AS user_id,
                    picking.company_id AS company_id,
                    MIN(pol.date_planned) AS date_planned,
                    picking.date_done AS date_done,
                    GREATEST(EXTRACT(epoch FROM picking.date_done - MIN(pol.date_planned)) / 86400, 0)::decimal(16, 2)
                        AS delay,
                    CASE WHEN picking.date_done::date <= MIN(pol.date_planned)::date THEN 100 ELSE 0 END
                        AS on_time_rate
                FROM stock_picking picking
                JOIN stock_picking_type picking_type ON picking_type.id = picking.picking_type_id
                JOIN stock_move move ON move.picking_id = picking.id
                JOIN purchase_order_line pol ON pol.id = move.purchase_line_id
                JOIN purchase_order po ON po.id = pol.order_id
                WHERE picking.state = 'done'
                  AND picking_type.code = 'incoming'
                  AND picking.date_done IS NOT NULL
                GROUP BY picking.id, po.id
            )
        """ % self._table)
