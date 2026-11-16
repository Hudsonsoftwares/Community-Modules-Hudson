# -*- coding: utf-8 -*-
import logging
from collections import defaultdict

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

PENDING_RX_STATES = ('confirmed', 'partially_dispensed')


class PosOrder(models.Model):
    _inherit = 'pos.order'

    dental_dispense_ids = fields.One2many(
        'dental.pharmacy.dispense', 'pos_order_id', string='Pharmacy Dispenses', readonly=True)
    dental_dispense_count = fields.Integer(compute='_compute_dental_dispense_count', string='Dispense Count')
    dental_is_pharmacy = fields.Boolean(related='config_id.dental_pharmacy_counter', string='Pharmacy Counter Order')

    @api.depends('dental_dispense_ids')
    def _compute_dental_dispense_count(self):
        for order in self:
            order.dental_dispense_count = len(order.dental_dispense_ids)

    # ------------------------------------------------------------------
    # Order sync
    # ------------------------------------------------------------------
    @api.model
    def _process_order(self, order, existing_order):
        session = self.env['pos.session'].browse(order.get('session_id'))
        config = session.config_id
        if config.dental_pharmacy_counter and order.get('state') != 'draft':
            # Every pharmacy sale is invoiced; a walk-in sale goes to the walk-in customer
            if not order.get('partner_id') and config.dental_walkin_partner_id:
                order['partner_id'] = config.dental_walkin_partner_id.id
            if order.get('partner_id'):
                order['to_invoice'] = True
        return super()._process_order(order, existing_order)

    def _process_saved_order(self, draft):
        result = super()._process_saved_order(draft)
        if not draft and self.state not in ('draft', 'cancel') and self._dental_needs_dispense_sync():
            self._dental_sync_dispense()
        return result

    def _dental_needs_dispense_sync(self):
        self.ensure_one()
        return self.config_id.dental_pharmacy_counter or any(
            self.lines.mapped('dental_prescription_line_id')) or any(
            self.lines.refunded_orderline_id.mapped('dental_dispense_line_id'))

    def _should_create_picking_real_time(self):
        # The pharmacy record points to the stock transfer, and the shelf must be up to date immediately
        if self.config_id.dental_pharmacy_counter:
            return True
        return super()._should_create_picking_real_time()

    # ------------------------------------------------------------------
    # Dispense records
    # ------------------------------------------------------------------
    def _dental_sync_dispense(self):
        """Mirror the paid POS order in the pharmacy: dispense records, prescription quantities and states.

        A paid order is never rejected here (the money is already taken); anything that breaks a
        pharmacy rule is recorded on the dispense as an exception for the pharmacy manager to review.
        """
        self.ensure_one()
        order = self.sudo()
        goods = order.lines.filtered(lambda l: l.product_id.type == 'consu' and not l.dental_dispense_line_id)
        refund_lines = goods.filtered(lambda l: l.qty < 0 and l.refunded_orderline_id)
        sale_lines = goods.filtered(lambda l: l.qty > 0)
        if refund_lines:
            order._dental_process_refund(refund_lines)
        if sale_lines:
            order._dental_create_dispenses(sale_lines)

    def _dental_lock_prescription_lines(self, rx_lines):
        if rx_lines:
            self.env.cr.execute('SELECT id FROM dental_prescription_line WHERE id IN %s FOR UPDATE',
                                [tuple(rx_lines.ids)])
            rx_lines.invalidate_recordset(['dispensed_qty', 'remaining_qty'])

    def _dental_find_lot(self, line):
        lot_names = [name for name in line.pack_lot_ids.mapped('lot_name') if name]
        if not lot_names:
            return self.env['stock.lot']
        return self.env['stock.lot'].sudo().search([
            ('name', '=', lot_names[0]),
            ('product_id', '=', line.product_id.id),
            ('company_id', 'in', (self.company_id.id, False)),
        ], limit=1)

    def _dental_create_dispenses(self, lines):
        self.ensure_one()
        today = fields.Date.context_today(self)
        partner = self.partner_id or self.config_id.dental_walkin_partner_id
        location = self.config_id._dental_stock_location() or self.picking_ids[:1].location_id
        dest_location = self.picking_ids[:1].location_dest_id or self.env.ref(
            'stock.stock_location_customers', raise_if_not_found=False)
        rx_lines = lines.mapped('dental_prescription_line_id')
        self._dental_lock_prescription_lines(rx_lines)

        by_prescription = defaultdict(lambda: self.env['pos.order.line'])
        for line in lines:
            by_prescription[line.dental_prescription_line_id.prescription_id] |= line

        Dispense = self.env['dental.pharmacy.dispense'].sudo().with_context(dental_pos_sync=True)
        dispenses = Dispense.browse()
        for rx, rx_pos_lines in by_prescription.items():
            exceptions = []
            if rx:
                if rx.state not in PENDING_RX_STATES:
                    exceptions.append(_("Prescription %(rx)s was not waiting at the pharmacy (status: %(state)s).",
                                        rx=rx.name, state=rx.state))
                if rx.patient_id != partner:
                    exceptions.append(_("Prescription %(rx)s belongs to %(patient)s but the order was billed to %(customer)s.",
                                        rx=rx.name, patient=rx.patient_id.display_name, customer=partner.display_name))
                if rx.company_id != self.company_id:
                    exceptions.append(_("Prescription %(rx)s belongs to another branch (%(company)s).",
                                        rx=rx.name, company=rx.company_id.name))
            line_vals = []
            for line in rx_pos_lines:
                product = line.product_id
                lot = self._dental_find_lot(line)
                rx_line = line.dental_prescription_line_id
                if product.tracking != 'none' and not lot:
                    exceptions.append(_("%s was sold without a batch number.", product.display_name))
                if lot and lot.expiry_date and lot.expiry_date < today:
                    exceptions.append(_("Batch %(lot)s of %(med)s expired on %(date)s.",
                                        lot=lot.name, med=product.display_name, date=lot.expiry_date))
                if rx_line and product.uom_id.compare(line.qty, rx_line.remaining_qty) > 0:
                    exceptions.append(_("%(med)s: %(qty)s sold but only %(rem)s remained on the prescription.",
                                        med=product.display_name, qty=line.qty, rem=rx_line.remaining_qty))
                if not rx_line and getattr(product, 'prescription_required', False):
                    exceptions.append(_("%s requires a prescription but was sold without one.", product.display_name))
                line_vals.append((0, 0, {
                    'prescription_line_id': rx_line.id or False,
                    'medicine_id': product.id,
                    'lot_id': lot.id or False,
                    'qty_to_dispense': line.qty,
                    'unit_price': line.price_subtotal / line.qty if line.qty else line.price_unit,
                    'pos_order_line_id': line.id,
                }))
            dispense = Dispense.create({
                'sale_type': 'prescription' if rx else 'otc',
                'prescription_id': rx.id or False,
                'patient_id': partner.id,
                'dentist_id': rx.dentist_id.id or False,
                'case_id': rx.case_id.id or False,
                'dispense_date': self.date_order or fields.Datetime.now(),
                'pharmacist_id': self.user_id.id or self.env.uid,
                'location_id': location.id,
                'location_dest_id': dest_location.id,
                'picking_id': self.picking_ids[:1].id or False,
                'invoice_id': self.account_move.id or False,
                'company_id': self.company_id.id,
                'pos_order_id': self.id,
                'state': 'dispensed',
                'pos_exception': bool(exceptions),
                'pos_exception_note': '\n'.join(exceptions) or False,
                'line_ids': line_vals,
            })
            for dline in dispense.line_ids:
                dline.pos_order_line_id.dental_dispense_line_id = dline
                if dline.prescription_line_id:
                    dline.prescription_line_id.dispensed_qty += dline.qty_to_dispense
            dispense.message_post(body=_("Dispensed and paid at the pharmacy counter %(config)s (POS order %(order)s).",
                                         config=self.config_id.name, order=self.name))
            if exceptions:
                dispense.message_post(body=_("Pharmacy rule exceptions to review:\n%s", '\n'.join(exceptions)))
                _logger.warning("POS order %s: pharmacy exceptions on %s: %s", self.name, dispense.name, exceptions)
            if rx:
                rx._update_dispensing_state()
                rx.message_post(body=_("Dispensed at the pharmacy counter: %(disp)s (POS order %(order)s).",
                                       disp=dispense.name, order=self.name))
            dispenses |= dispense

        self._dental_link_invoice(dispenses)
        return dispenses

    def _dental_link_invoice(self, dispenses):
        invoice = self.account_move.sudo()
        if not invoice or not dispenses:
            return
        main = dispenses.filtered('prescription_id')[:1] or dispenses[:1]
        vals = {'pharmacy_dispense_id': main.id}
        if main.prescription_id:
            vals['dental_prescription_id'] = main.prescription_id.id
        if main.case_id and 'dental_case_id' in invoice._fields:
            vals['dental_case_id'] = main.case_id.id
        invoice.write(vals)

    def _dental_process_refund(self, lines):
        """A POS refund gives the medicine back: lower the dispensed quantities and mark the dispense returned."""
        self.ensure_one()
        affected = self.env['dental.pharmacy.dispense']
        rx_lines = lines.refunded_orderline_id.dental_dispense_line_id.prescription_line_id
        self._dental_lock_prescription_lines(rx_lines)
        for line in lines:
            dline = line.refunded_orderline_id.dental_dispense_line_id
            if not dline:
                continue
            qty = min(abs(line.qty), dline.qty_to_dispense - dline.qty_returned)
            if line.product_id.uom_id.is_zero(qty):
                continue
            dline.qty_returned += qty
            line.dental_dispense_line_id = dline
            if dline.prescription_line_id:
                rx_line = dline.prescription_line_id
                rx_line.dispensed_qty = max(0.0, rx_line.dispensed_qty - qty)
            affected |= dline.dispense_id
        for dispense in affected:
            fully_returned = all(
                l.medicine_id.uom_id.compare(l.qty_returned, l.qty_to_dispense) >= 0 for l in dispense.line_ids)
            if fully_returned:
                dispense.write({
                    'state': 'returned',
                    'returned_date': fields.Datetime.now(),
                    'returned_by_id': self.user_id.id or self.env.uid,
                    'return_picking_id': self.picking_ids[:1].id or False,
                    'return_reason': _("Refunded at the pharmacy counter (POS order %s).", self.name),
                })
            dispense.message_post(body=_("%(what)s refunded at the pharmacy counter (POS order %(order)s).",
                                         what=_("Fully") if fully_returned else _("Partly"), order=self.name))
            if dispense.prescription_id:
                dispense.prescription_id._update_dispensing_state()
                dispense.prescription_id.message_post(body=_("Medicines of %(disp)s refunded at the pharmacy counter (POS order %(order)s).",
                                                             disp=dispense.name, order=self.name))
        return affected

    def action_view_dental_dispenses(self):
        self.ensure_one()
        action = {
            'name': _('Pharmacy Dispenses'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.pharmacy.dispense',
            'domain': [('id', 'in', self.dental_dispense_ids.ids)],
            'view_mode': 'list,form',
        }
        if len(self.dental_dispense_ids) == 1:
            action.update(view_mode='form', res_id=self.dental_dispense_ids.id)
        return action
