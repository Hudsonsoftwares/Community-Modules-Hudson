# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    dental_prescription_line_id = fields.Many2one(
        'dental.prescription.line', string='Prescription Line', index='btree_not_null', readonly=True,
        copy=False, compute='_compute_dental_prescription_line_id', store=True)
    # The POS client does not load prescription lines, so it sends the link as a plain id
    dental_rx_line_ref = fields.Integer(string='Prescription Line Ref', copy=False)
    dental_dispense_line_id = fields.Many2one(
        'dental.pharmacy.dispense.line', string='Dispense Line', readonly=True, copy=False, index='btree_not_null')

    @api.depends('dental_rx_line_ref')
    def _compute_dental_prescription_line_id(self):
        RxLine = self.env['dental.prescription.line'].sudo()
        for line in self:
            rx_line = RxLine.browse(line.dental_rx_line_ref).exists() if line.dental_rx_line_ref else RxLine
            line.dental_prescription_line_id = rx_line.id or False

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        if result:
            result.append('dental_rx_line_ref')
        return result

    @api.model
    def get_existing_lots(self, company_id, config_id, product_id):
        """At a pharmacy counter: expired batches are never offered and batches come earliest-expiry first."""
        lots = super().get_existing_lots(company_id, config_id, product_id)
        config = self.env['pos.config'].browse(config_id)
        if not config.dental_pharmacy_counter or not lots:
            return lots
        today = fields.Date.context_today(self)
        records = {lot.id: lot for lot in self.env['stock.lot'].sudo().browse([l['id'] for l in lots])}
        result = []
        for lot in lots:
            expiry = records[lot['id']].expiry_date
            if expiry and expiry < today:
                continue
            lot['dental_expiry_date'] = fields.Date.to_string(expiry) if expiry else False
            if not lot.get('expiration_date') and expiry:
                lot['expiration_date'] = fields.Datetime.to_string(fields.Datetime.to_datetime(expiry))
            result.append(lot)
        result.sort(key=lambda l: (not l['dental_expiry_date'], l['dental_expiry_date'] or '', l['name']))
        return result
