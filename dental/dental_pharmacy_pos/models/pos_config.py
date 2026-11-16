# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import html2plaintext

PENDING_RX_STATES = ('confirmed', 'partially_dispensed')


class PosConfig(models.Model):
    _inherit = 'pos.config'

    dental_pharmacy_counter = fields.Boolean(
        string='Pharmacy Counter',
        help='This point of sale is a pharmacy counter: it loads doctor prescriptions, warns about allergies, '
             'sells medicines from the earliest-expiring batch, refuses expired batches and invoices every order.')
    dental_walkin_partner_id = fields.Many2one(
        'res.partner', string='Walk-in Customer',
        default=lambda self: self.env.ref('dental_pharmacy_pos.partner_pharmacy_walkin', raise_if_not_found=False),
        help='Customer used on the invoice of a walk-in sale when the cashier does not select a customer.')
    dental_rx_lookback_days = fields.Integer(
        string='Show Prescriptions Of The Last (Days)', default=90,
        help='Pending prescriptions older than this are not listed at the counter. 0 = no limit.')

    @api.constrains('dental_pharmacy_counter', 'dental_walkin_partner_id')
    def _check_dental_walkin_partner(self):
        for config in self:
            if config.dental_pharmacy_counter and not config.dental_walkin_partner_id:
                raise ValidationError(_("Set a Walk-in Customer on the pharmacy counter %s: every sale is invoiced.",
                                        config.name))

    # ------------------------------------------------------------------
    # Data for the counter (called from the POS)
    # ------------------------------------------------------------------
    def _dental_check_counter_access(self):
        self.ensure_one()
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_("Only Point of Sale users can read prescriptions at the counter."))
        if not self.dental_pharmacy_counter:
            raise AccessError(_("%s is not a pharmacy counter.", self.name))
        if self.company_id not in self.env.user.company_ids:
            raise AccessError(_("You have no access to the branch %s.", self.company_id.name))

    def _dental_stock_location(self):
        self.ensure_one()
        return self.picking_type_id.default_location_src_id

    def _dental_available_qty(self, products):
        """Sellable quantity per product in the counter's stock location (expired batches excluded)."""
        self.ensure_one()
        location = self._dental_stock_location()
        if not location or not products:
            return {}
        today = fields.Date.context_today(self)
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', 'in', products.ids),
            ('location_id', 'child_of', location.id),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
        ])
        result = dict.fromkeys(products.ids, 0.0)
        for quant in quants:
            if quant.lot_id and quant.lot_id.expiry_date and quant.lot_id.expiry_date < today:
                continue
            result[quant.product_id.id] += quant.quantity - quant.reserved_quantity
        return result

    def _dental_selection_label(self, record, field_name):
        value = record[field_name]
        if not value:
            return ''
        return dict(record._fields[field_name]._description_selection(self.env)).get(value, value)

    def _dental_allergy_info(self, partner):
        status = partner.allergy_status if 'allergy_status' in partner._fields else False
        text = ''
        if 'allergies' in partner._fields and partner.allergies:
            text = ' '.join(html2plaintext(partner.allergies).split())
        return {
            'status': status or 'unknown',
            'status_label': self._dental_selection_label(partner, 'allergy_status') if status else _('Not Recorded'),
            'text': text,
        }

    def _dental_prescription_vals(self, rx, stock):
        lines = []
        for line in rx.line_ids.filtered(lambda l: l.medicine_id and l.remaining_qty > 0):
            product = line.medicine_id
            lines.append({
                'id': line.id,
                'product_id': product.id,
                'product_tmpl_id': product.product_tmpl_id.id,
                'medicine': product.display_name,
                'generic_name': product.generic_name or '',
                'strength': product.strength or '',
                'dosage_form': self._dental_selection_label(product, 'dosage_form'),
                'route': self._dental_selection_label(line, 'route'),
                'frequency': line.frequency_label or '',
                'duration': line.duration,
                'instructions': line.instructions or '',
                'quantity': line.quantity,
                'dispensed_qty': line.dispensed_qty,
                'remaining_qty': line.remaining_qty,
                'uom': line.uom_id.name or '',
                'available_qty': stock.get(product.id, 0.0),
                'tracked': product.tracking != 'none',
                'available_in_pos': product.available_in_pos and product.sale_ok,
                'allergy_conflict': line.has_allergy_conflict,
                'allergy_note': line.allergy_conflict_note or '',
            })
        return {
            'id': rx.id,
            'name': rx.name,
            'date': fields.Date.to_string(rx.prescription_date),
            'state': rx.state,
            'state_label': self._dental_selection_label(rx, 'state'),
            'partner_id': rx.patient_id.id,
            'patient': rx.patient_id.display_name,
            'patient_ref': rx.patient_id.dental_patient_id if 'dental_patient_id' in rx.patient_id._fields else '',
            'patient_phone': rx.patient_id.phone or '',
            'dentist': rx.dentist_id.name or '',
            'case': rx.case_id.display_name if rx.case_id else '',
            'allergy': self._dental_allergy_info(rx.patient_id),
            'lines': lines,
        }

    def dental_get_prescriptions(self, partner_id=False, search=''):
        """Pending prescriptions of the counter's branch, optionally of one patient or matching a search."""
        self._dental_check_counter_access()
        domain = [('company_id', '=', self.company_id.id), ('state', 'in', PENDING_RX_STATES)]
        if self.dental_rx_lookback_days:
            since = fields.Date.context_today(self) - timedelta(days=self.dental_rx_lookback_days)
            domain.append(('prescription_date', '>=', since))
        if partner_id:
            domain.append(('patient_id', '=', partner_id))
        search = (search or '').strip()
        if search:
            domain += ['|', '|', '|', ('name', 'ilike', search), ('patient_id.name', 'ilike', search),
                       ('patient_id.phone', 'ilike', search), ('patient_id.dental_patient_id', 'ilike', search)]
        prescriptions = self.env['dental.prescription'].sudo().search(domain, limit=80)
        stock = self._dental_available_qty(prescriptions.line_ids.medicine_id)
        result = [self._dental_prescription_vals(rx, stock) for rx in prescriptions]
        return [vals for vals in result if vals['lines']]

    def dental_count_prescriptions(self, partner_id):
        self._dental_check_counter_access()
        return len(self.dental_get_prescriptions(partner_id=partner_id))

    def dental_get_patient_info(self, partner_id):
        """Allergy alert, pending prescription count and recent medicine history of a patient."""
        self._dental_check_counter_access()
        partner = self.env['res.partner'].sudo().browse(partner_id).exists()
        if not partner:
            return {}
        lines = self.env['dental.pharmacy.dispense.line'].sudo().search([
            ('dispense_id.patient_id', '=', partner.id),
            ('dispense_id.state', 'in', ('dispensed', 'returned')),
        ], order='id desc', limit=15)
        history = [{
            'date': fields.Datetime.to_string(line.dispense_id.dispense_date),
            'reference': line.dispense_id.name,
            'prescription': line.dispense_id.prescription_id.name or '',
            'medicine': line.medicine_id.display_name,
            'qty': line.qty_to_dispense,
            'returned': line.dispense_id.state == 'returned',
        } for line in lines]
        is_patient = partner.is_dental_patient if 'is_dental_patient' in partner._fields else False
        return {
            'partner_id': partner.id,
            'is_patient': is_patient,
            'is_walkin': partner == self.dental_walkin_partner_id,
            'allergy': self._dental_allergy_info(partner),
            'pending_count': len(self.dental_get_prescriptions(partner_id=partner.id)) if is_patient else 0,
            'history': history,
        }
