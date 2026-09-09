# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    subscription_count = fields.Integer(
        string='Subscriptions',
        compute='_compute_subscription_count'
    )

    def _compute_subscription_count(self):
        subscription_data = self.env['sale.order'].read_group(
            domain=[('is_subscription', '=', True), ('partner_id', 'in', self.ids)],
            fields=['partner_id'],
            groupby=['partner_id']
        )
        mapped_data = {data['partner_id'][0]: data['partner_id_count'] for data in subscription_data}
        for partner in self:
            partner.subscription_count = mapped_data.get(partner.id, 0)

    def action_view_subscriptions(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('hudson_subscriptions.action_subscription_orders')
        action['domain'] = [('is_subscription', '=', True), ('partner_id', '=', self.id)]
        action['context'] = {'default_partner_id': self.id, 'default_is_subscription': True}
        return action
