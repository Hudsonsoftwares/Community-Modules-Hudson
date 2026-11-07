# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, tools


class SaleSubscriptionLineReport(models.Model):
    """ The lines of the subscriptions with their monthly recurring revenue, to break the MRR down by product,
    category, plan or customer country.
    """
    _name = 'sale.subscription.line.report'
    _description = 'Subscription Lines Analysis'
    _auto = False
    _order = 'order_id desc, id'

    order_id = fields.Many2one('sale.order', string='Subscription', readonly=True)
    product_id = fields.Many2one('product.product', string='Product Variant', readonly=True)
    product_tmpl_id = fields.Many2one('product.template', string='Product', readonly=True)
    categ_id = fields.Many2one('product.category', string='Product Category', readonly=True)
    template_id = fields.Many2one('sale.order.template', string='Plan', readonly=True)
    plan_id = fields.Many2one('sale.subscription.plan', string='Recurrence', readonly=True)
    subscription_state = fields.Selection(selection='_selection_subscription_state', string='Subscription Status',
                                          readonly=True)
    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    country_id = fields.Many2one('res.country', string='Country', readonly=True)
    user_id = fields.Many2one('res.users', string='Salesperson', readonly=True)
    team_id = fields.Many2one('crm.team', string='Sales Team', readonly=True)
    source_id = fields.Many2one('utm.source', string='Source', readonly=True)
    medium_id = fields.Many2one('utm.medium', string='Medium', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
    recurring_monthly = fields.Monetary(string='MRR', readonly=True, currency_field='currency_id')

    @api.model
    def _selection_subscription_state(self):
        return self.env['sale.order']._fields['subscription_state'].selection

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT line.id AS id,
                       so.id AS order_id,
                       line.product_id AS product_id,
                       product.product_tmpl_id AS product_tmpl_id,
                       template.categ_id AS categ_id,
                       so.sale_order_template_id AS template_id,
                       so.plan_id AS plan_id,
                       so.subscription_state AS subscription_state,
                       so.partner_id AS partner_id,
                       partner.country_id AS country_id,
                       so.user_id AS user_id,
                       so.team_id AS team_id,
                       so.source_id AS source_id,
                       so.medium_id AS medium_id,
                       so.company_id AS company_id,
                       so.currency_id AS currency_id,
                       line.recurring_monthly AS recurring_monthly
                  FROM sale_order_line line
                  JOIN sale_order so ON so.id = line.order_id
                  JOIN product_product product ON product.id = line.product_id
                  JOIN product_template template ON template.id = product.product_tmpl_id
             LEFT JOIN res_partner partner ON partner.id = so.partner_id
                 WHERE so.is_subscription AND NOT COALESCE(so.is_upsell, FALSE) AND line.display_type IS NULL
            )
        """ % self._table)
