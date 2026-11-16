# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DentalPrescription(models.Model):
    _inherit = 'dental.prescription'

    dispense_at_pos = fields.Boolean(
        string='Dispensed At POS Counter', compute='_compute_dispense_at_pos',
        help="The branch dispenses and bills medicines at the Point of Sale pharmacy counter.")
    pos_order_count = fields.Integer(string='POS Orders', compute='_compute_pos_order_count')

    @api.depends('company_id.dental_dispense_mode', 'company_id.dental_has_pharmacy')
    def _compute_dispense_at_pos(self):
        for rx in self:
            rx.dispense_at_pos = bool(rx.company_id) and rx.company_id._dental_dispenses_at_pos()

    def _compute_pos_order_count(self):
        for rx in self:
            rx.pos_order_count = len(rx.sudo().dispense_ids.pos_order_id)

    def _create_sale_order(self):
        """At a POS counter the paid POS order is the sale: no quotation is created."""
        self.ensure_one()
        if self.company_id._dental_dispenses_at_pos():
            return self.env['sale.order']
        return super()._create_sale_order()

    def action_dispense(self):
        for rx in self:
            if rx.company_id._dental_dispenses_at_pos() and not self.env.user.has_group(
                    'dental_pharmacy.group_dental_pharmacy_manager'):
                raise UserError(_("%(branch)s dispenses at the Point of Sale pharmacy counter. "
                                  "Load prescription %(rx)s at the counter.", branch=rx.company_id.name, rx=rx.name))
        return super().action_dispense()

    def action_view_pos_orders(self):
        self.ensure_one()
        orders = self.sudo().dispense_ids.pos_order_id
        action = {
            'name': _('POS Orders'),
            'type': 'ir.actions.act_window',
            'res_model': 'pos.order',
            'domain': [('id', 'in', orders.ids)],
            'view_mode': 'list,form',
        }
        if len(orders) == 1:
            action.update(view_mode='form', res_id=orders.id)
        return action
