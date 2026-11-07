# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import fields, models, tools

STARTED_STATES = ('3_progress', '4_paused', '5_renew', '5_renewed', '6_churn')


class SaleSubscriptionEventReport(models.Model):
    """ The MRR changes of the subscriptions, like the subscription logs of Odoo Enterprise, derived from the orders:
    a new subscription at its start date, the MRR added (or removed) by a confirmed upsell or by a renewal at another
    price, and the lost MRR of a churned subscription at its close date.
    """
    _name = 'sale.subscription.event.report'
    _description = 'Subscription MRR Changes'
    _auto = False
    _order = 'event_date desc, id desc'

    order_id = fields.Many2one('sale.order', string='Subscription', readonly=True)
    event_type = fields.Selection([
        ('0_creation', 'New'),
        ('1_expansion', 'Expansion'),
        ('15_contraction', 'Contraction'),
        ('2_churn', 'Churn'),
    ], string='Type of Event', readonly=True)
    event_date = fields.Date(string='Event Date', readonly=True)
    amount_signed = fields.Monetary(string='MRR Change', readonly=True, currency_field='currency_id')
    recurring_monthly = fields.Monetary(string='MRR', readonly=True, currency_field='currency_id',
                                        help="Current monthly recurring revenue of the subscription")
    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    country_id = fields.Many2one('res.country', string='Country', readonly=True)
    user_id = fields.Many2one('res.users', string='Salesperson', readonly=True)
    team_id = fields.Many2one('crm.team', string='Sales Team', readonly=True)
    plan_id = fields.Many2one('sale.subscription.plan', string='Recurrence', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %(table)s AS (
                WITH upsell AS (
                    SELECT origin_order_id AS order_id, SUM(recurring_monthly) AS amount
                      FROM sale_order
                     WHERE is_subscription AND is_upsell AND state = 'sale'
                  GROUP BY origin_order_id
                ), event AS (
                    -- New subscriptions (renewals and upsells continue an existing one)
                    SELECT so.id * 4 AS id, so.id AS order_id, '0_creation' AS event_type,
                           so.start_date AS event_date, so.recurring_monthly AS amount_signed
                      FROM sale_order so
                     WHERE so.is_subscription AND NOT COALESCE(so.is_upsell, FALSE)
                       AND NOT COALESCE(so.is_renewal, FALSE) AND so.start_date IS NOT NULL
                       AND so.subscription_state IN %(states)s
                    UNION ALL
                    -- Confirmed upsells
                    SELECT so.id * 4 + 1, so.origin_order_id,
                           CASE WHEN so.recurring_monthly < 0 THEN '15_contraction' ELSE '1_expansion' END,
                           COALESCE(so.date_order::date, so.start_date), so.recurring_monthly
                      FROM sale_order so
                     WHERE so.is_subscription AND so.is_upsell AND so.state = 'sale'
                       AND so.origin_order_id IS NOT NULL AND so.recurring_monthly <> 0
                    UNION ALL
                    -- Renewals at another price
                    SELECT so.id * 4 + 2, so.id,
                           CASE WHEN so.recurring_monthly < origin.recurring_monthly
                                THEN '15_contraction' ELSE '1_expansion' END,
                           so.start_date, so.recurring_monthly - origin.recurring_monthly
                      FROM sale_order so
                      JOIN sale_order origin ON origin.id = so.origin_order_id
                     WHERE so.is_subscription AND so.is_renewal AND so.start_date IS NOT NULL
                       AND so.subscription_state IN %(states)s
                       AND so.recurring_monthly <> origin.recurring_monthly
                    UNION ALL
                    -- Churned subscriptions lose their MRR and the MRR of their upsells
                    SELECT so.id * 4 + 3, so.id, '2_churn',
                           COALESCE(so.close_date, so.end_date, so.write_date::date),
                           -(so.recurring_monthly + COALESCE(upsell.amount, 0))
                      FROM sale_order so
                 LEFT JOIN upsell ON upsell.order_id = so.id
                     WHERE so.is_subscription AND NOT COALESCE(so.is_upsell, FALSE)
                       AND so.subscription_state = '6_churn'
                )
                SELECT event.id, event.order_id, event.event_type, event.event_date, event.amount_signed,
                       so.recurring_monthly, so.partner_id, partner.country_id, so.user_id, so.team_id,
                       so.plan_id, so.company_id, so.currency_id
                  FROM event
                  JOIN sale_order so ON so.id = event.order_id
             LEFT JOIN res_partner partner ON partner.id = so.partner_id
            )
        """ % {
            'table': self._table,
            'states': "('%s')" % "', '".join(STARTED_STATES),
        })
