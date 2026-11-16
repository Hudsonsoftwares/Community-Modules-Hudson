# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.common import TestPoSCommon


@tagged('post_install', '-at_install')
class TestPosPharmacy(TestPoSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.group_ids |= (
            cls.env.ref('dental_base.group_dental_manager')
            | cls.env.ref('dental_pharmacy.group_dental_pharmacist')
            | cls.env.ref('point_of_sale.group_pos_user')
        )
        cls.company.write({'dental_has_pharmacy': True, 'dental_dispense_mode': 'pos'})
        cls.walkin = cls.env.ref('dental_pharmacy_pos.partner_pharmacy_walkin')
        cls.config = cls.basic_config
        cls.config.write({'dental_pharmacy_counter': True, 'dental_walkin_partner_id': cls.walkin.id})

        cls.patient = cls.env['res.partner'].create({
            'name': 'POS Rx Patient', 'is_dental_patient': True, 'allergy_status': 'none'})
        cls.other_patient = cls.env['res.partner'].create({'name': 'Other Rx Patient', 'is_dental_patient': True})
        cls.dentist = cls.env['hr.employee'].sudo().create({
            'name': 'Dr. Counter', 'dental_role': 'dentist', 'registration_number': 'POS-1'})

        cls.medicine = cls.env['product.product'].create({
            'name': 'Amoxicillin 500 POS', 'is_medicine': True, 'is_storable': True, 'tracking': 'lot',
            'dosage_form': 'capsule', 'strength': '500 mg', 'lst_price': 10.0, 'taxes_id': [Command.clear()],
        })
        cls.location = cls.config.picking_type_id.default_location_src_id
        today = date.today()
        cls.lot_late = cls.env['stock.lot'].create({
            'name': 'AMX-LATE', 'product_id': cls.medicine.id, 'expiry_date': today + timedelta(days=300)})
        cls.lot_soon = cls.env['stock.lot'].create({
            'name': 'AMX-SOON', 'product_id': cls.medicine.id, 'expiry_date': today + timedelta(days=40)})
        cls.lot_expired = cls.env['stock.lot'].create({
            'name': 'AMX-OLD', 'product_id': cls.medicine.id, 'expiry_date': today - timedelta(days=5)})
        Quant = cls.env['stock.quant']
        for lot in (cls.lot_late, cls.lot_soon, cls.lot_expired):
            Quant._update_available_quantity(cls.medicine, cls.location, 50, lot_id=lot)

    def _make_prescription(self, qty=10.0, patient=None):
        rx = self.env['dental.prescription'].create({
            'patient_id': (patient or self.patient).id,
            'dentist_id': self.dentist.id,
            'line_ids': [Command.create({
                'medicine_id': self.medicine.id, 'quantity': qty, 'frequency': 'tid', 'duration': 5})],
        })
        rx.action_confirm()
        return rx

    def _line(self, qty, rx_line=None, lot=None, **kwargs):
        vals = {'product': self.medicine, 'quantity': qty, **kwargs}
        if rx_line:
            vals['dental_rx_line_ref'] = rx_line.id
        if lot:
            vals['pack_lot_ids'] = [Command.create({'lot_name': lot.name})]
        return vals

    def _sync(self, lines, customer=False):
        data = self.create_ui_order_data(lines, customer=customer)
        data['state'] = 'paid'
        self.env['pos.order'].sync_from_ui([data])
        return self.env['pos.order'].search([('uuid', '=', data['uuid'])])

    # ------------------------------------------------------------------
    def test_01_confirm_in_pos_mode_creates_no_quotation(self):
        rx = self._make_prescription()
        self.assertEqual(rx.state, 'confirmed')
        self.assertFalse(rx.sale_order_id, "A POS-counter branch must not create a sales quotation")
        self.assertTrue(rx.dispense_at_pos)

    def test_02_counter_lists_prescription_and_fefo_lots(self):
        rx = self._make_prescription()
        self.open_new_session()
        result = self.config.dental_get_prescriptions(self.patient.id, '')
        self.assertEqual([r['id'] for r in result], [rx.id])
        line = result[0]['lines'][0]
        self.assertEqual(line['remaining_qty'], 10.0)
        self.assertEqual(line['available_qty'], 100.0, "Expired stock is not sellable")
        info = self.config.dental_get_patient_info(self.patient.id)
        self.assertEqual(info['pending_count'], 1)
        self.assertEqual(info['allergy']['status'], 'none')

        lots = self.env['pos.order.line'].get_existing_lots(self.company.id, self.config.id, self.medicine.id)
        self.assertEqual([l['name'] for l in lots], ['AMX-SOON', 'AMX-LATE'],
                         "Expired batch hidden, earliest expiry first")

    def test_03_paid_order_dispenses_invoices_and_updates_prescription(self):
        rx = self._make_prescription(qty=10)
        rx_line = rx.line_ids
        self.open_new_session()
        order = self._sync([self._line(4, rx_line, self.lot_soon)], customer=self.patient)

        self.assertTrue(order.account_move, "Every pharmacy sale is invoiced")
        self.assertEqual(order.picking_ids.state, 'done', "Stock leaves the shelf when the order is paid")
        dispense = order.dental_dispense_ids
        self.assertEqual(len(dispense), 1)
        self.assertEqual(dispense.state, 'dispensed')
        self.assertEqual(dispense.prescription_id, rx)
        self.assertEqual(dispense.picking_id, order.picking_ids[:1])
        self.assertEqual(dispense.invoice_id, order.account_move)
        self.assertEqual(dispense.line_ids.lot_id, self.lot_soon)
        self.assertFalse(dispense.pos_exception, dispense.pos_exception_note)
        self.assertEqual(order.account_move.pharmacy_dispense_id, dispense)
        self.assertEqual(rx_line.dispensed_qty, 4)
        self.assertEqual(rx.state, 'partially_dispensed')
        self.assertEqual(rx.invoice_count, 1)
        self.assertEqual(self.medicine.with_context(location=self.location.id, lot_id=self.lot_soon.id).qty_available, 46)

        order2 = self._sync([self._line(6, rx_line, self.lot_soon)], customer=self.patient)
        self.assertEqual(rx_line.dispensed_qty, 10)
        self.assertEqual(rx.state, 'fully_dispensed')
        self.assertEqual(len(rx.dispense_ids), 2)
        self.assertEqual(rx.pos_order_count, 2)
        # Processing the same paid order again changes nothing
        order2._dental_sync_dispense()
        self.assertEqual(len(rx.dispense_ids), 2)
        self.assertEqual(rx_line.dispensed_qty, 10)

    def test_04_walkin_sale_is_invoiced_to_walkin_customer(self):
        self.open_new_session()
        order = self._sync([self._line(2, lot=self.lot_soon)])
        self.assertEqual(order.partner_id, self.walkin)
        self.assertTrue(order.account_move)
        dispense = order.dental_dispense_ids
        self.assertEqual(dispense.sale_type, 'otc')
        self.assertEqual(dispense.patient_id, self.walkin)

    def test_05_refund_reverses_dispense_and_prescription(self):
        rx = self._make_prescription(qty=10)
        self.open_new_session()
        order = self._sync([self._line(10, rx.line_ids, self.lot_soon)], customer=self.patient)
        self.assertEqual(rx.state, 'fully_dispensed')

        refund_line = self._line(-3, lot=self.lot_soon, refunded_orderline_id=order.lines.id)
        self._sync([refund_line], customer=self.patient)
        dispense = order.dental_dispense_ids
        self.assertEqual(dispense.line_ids.qty_returned, 3)
        self.assertEqual(dispense.state, 'dispensed', "Partly refunded stays dispensed")
        self.assertEqual(rx.line_ids.dispensed_qty, 7)
        self.assertEqual(rx.state, 'partially_dispensed')

        refund_line = self._line(-7, lot=self.lot_soon, refunded_orderline_id=order.lines.id)
        refund = self._sync([refund_line], customer=self.patient)
        self.assertEqual(dispense.state, 'returned')
        self.assertEqual(dispense.return_picking_id, refund.picking_ids[:1])
        self.assertEqual(rx.line_ids.dispensed_qty, 0)
        self.assertEqual(rx.state, 'confirmed')

    def test_06_rule_breaks_are_recorded_for_review(self):
        rx = self._make_prescription(qty=5)
        self.open_new_session()
        order = self._sync([self._line(8, rx.line_ids, self.lot_expired)], customer=self.other_patient)
        dispense = order.dental_dispense_ids
        self.assertTrue(dispense.pos_exception)
        note = dispense.pos_exception_note
        self.assertIn('AMX-OLD', note)
        self.assertIn('only 5', note)
        self.assertIn(self.patient.name, note)
        self.assertEqual(rx.line_ids.dispensed_qty, 8, "A paid sale is always recorded")

    def test_07_backend_dispense_is_manager_fallback_only(self):
        rx = self._make_prescription()
        self.env.user.group_ids -= self.env.ref('dental_pharmacy.group_dental_pharmacy_manager')
        self.assertFalse(self.env.user.has_group('dental_pharmacy.group_dental_pharmacy_manager'))
        with self.assertRaises(UserError):
            rx.action_dispense()

    def test_09_plain_cashier_can_sell_prescription(self):
        """A counter cashier with only Point of Sale rights (no inventory / pharmacy rights)."""
        rx = self._make_prescription(qty=3)
        cashier = self.env['res.users'].create({
            'name': 'Counter Cashier', 'login': 'counter_cashier',
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                       self.env.ref('point_of_sale.group_pos_user').id])],
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
        })
        self.open_new_session()
        config = self.config.with_user(cashier)
        self.assertEqual(len(config.dental_get_prescriptions(self.patient.id, '')), 1)
        lots = self.env['pos.order.line'].with_user(cashier).get_existing_lots(
            self.company.id, self.config.id, self.medicine.id)
        self.assertEqual(lots[0]['name'], 'AMX-SOON')
        data = self.create_ui_order_data([self._line(3, rx.line_ids, self.lot_soon)], customer=self.patient)
        self.env['pos.order'].with_user(cashier).sync_from_ui([data])
        order = self.env['pos.order'].search([('uuid', '=', data['uuid'])])
        self.assertEqual(order.dental_dispense_ids.state, 'dispensed')
        self.assertEqual(rx.state, 'fully_dispensed')

    def test_08_backend_mode_branch_is_unchanged(self):
        self.company.dental_dispense_mode = 'backend'
        rx = self._make_prescription()
        self.assertFalse(rx.dispense_at_pos)
        self.assertTrue(rx.sale_order_id, "Backend mode keeps the existing quotation flow")
        action = rx.action_dispense()
        self.assertEqual(action['res_model'], 'dental.pharmacy.dispense')
