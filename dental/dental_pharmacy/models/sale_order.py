# -*- coding: utf-8 -*-
from odoo import _, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    dental_prescription_id = fields.Many2one(
        'dental.prescription', string='Prescription', index='btree_not_null', copy=False, readonly=True,
        help='Clinical prescription this medicine order was created from.')

    def action_view_dental_prescription(self):
        self.ensure_one()
        return {
            'name': _('Prescription'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.prescription',
            'view_mode': 'form',
            'res_id': self.dental_prescription_id.id,
        }


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    dental_prescription_line_id = fields.Many2one(
        'dental.prescription.line', string='Prescription Line', index='btree_not_null', copy=False, readonly=True)


class DentalPrescriptionLine(models.Model):
    _inherit = 'dental.prescription.line'

    sale_line_ids = fields.One2many('sale.order.line', 'dental_prescription_line_id', string='Sales Order Lines', readonly=True)

    def _get_active_sale_line(self):
        self.ensure_one()
        return self.sudo().sale_line_ids.filtered(lambda l: l.order_id.state != 'cancel')[:1]
