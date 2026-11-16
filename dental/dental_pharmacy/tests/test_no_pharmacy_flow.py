# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'dental_no_pharmacy')
class TestPrescriptionFulfillment(TransactionCase):
    """Branches with a pharmacy route prescriptions to the pharmacy queue; branches without one
    issue them to the patient, and the clinic never bills those medicines."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        common = {'company_id': cls.company.id, 'company_ids': [cls.company.id]}
        cls.dentist_user = new_test_user(cls.env, login='rx_flow_dentist', groups='base.group_user,dental_base.group_dental_dentist', **common)
        cls.reception_user = new_test_user(cls.env, login='rx_flow_reception', groups='base.group_user,dental_base.group_dental_receptionist', **common)
        cls.plain_user = new_test_user(cls.env, login='rx_flow_plain', groups='base.group_user', **common)
        cls.doctor = cls.env['hr.employee'].create({'name': 'Dr. Flow', 'dental_role': 'dentist', 'user_id': cls.dentist_user.id})
        cls.patient = cls.env['res.partner'].create({'name': 'Flow Patient', 'is_dental_patient': True, 'phone': '9000000088',
                                                     'email': 'flow.patient@example.com'})
        cls.medicine = cls.env['product.product'].create({'name': 'Flow Ibuprofen 400', 'is_medicine': True, 'list_price': 5.0})

    def _new_rx(self):
        return self.env['dental.prescription'].with_user(self.dentist_user).create({
            'patient_id': self.patient.id,
            'dentist_id': self.doctor.id,
            'line_ids': [(0, 0, {'medicine_id': self.medicine.id, 'dose': '1 tab', 'frequency': 'bid', 'duration': 3, 'quantity': 6})],
        })

    def test_branch_with_pharmacy_sends_to_pharmacy(self):
        self.company.dental_has_pharmacy = True
        rx = self._new_rx()
        rx.action_confirm()
        self.assertEqual(rx.state, 'confirmed')
        self.assertEqual(rx.fulfillment, 'pharmacy')

    def test_branch_without_pharmacy_issues_to_patient(self):
        self.company.dental_has_pharmacy = False
        rx = self._new_rx()
        rx.action_confirm()
        self.assertEqual(rx.state, 'issued')
        self.assertEqual(rx.fulfillment, 'patient')
        self.assertTrue(rx.issued_date)
        # Emailed to the patient with the prescription PDF
        mail_msg = rx.message_ids.filtered(lambda m: m.message_type == 'comment' and self.patient in m.partner_ids)
        self.assertTrue(mail_msg, "The prescription must be emailed to the patient")
        self.assertTrue(mail_msg.attachment_ids, "The prescription PDF must be attached")
        # Not in the pharmacy queue and cannot be dispensed or billed by the clinic
        with self.assertRaises(UserError):
            rx.with_user(self.dentist_user).sudo().action_dispense()
        self.assertFalse(self.env['account.move'].search([('dental_prescription_id', '=', rx.id)]))

    def test_reception_can_hand_over(self):
        self.company.dental_has_pharmacy = True
        rx = self._new_rx()
        rx.action_confirm()
        rx_reception = rx.with_user(self.reception_user)
        rx_reception.action_issue_to_patient()
        self.assertEqual(rx.state, 'issued')
        self.assertEqual(rx_reception.action_print_for_patient()['type'], 'ir.actions.report')
        rx_reception.action_send_to_patient()

    def test_hand_over_requires_dental_role(self):
        self.company.dental_has_pharmacy = False
        rx = self._new_rx()
        rx.action_confirm()
        with self.assertRaises(AccessError):
            rx.with_user(self.plain_user).action_send_to_patient()

    def test_complete_consultation_releases_draft_prescriptions(self):
        self.company.dental_has_pharmacy = False
        case = self.env['dental.case'].create({'patient_id': self.patient.id, 'doctor_id': self.doctor.id,
                                               'chief_complaint': 'Tooth pain'})
        rx = self._new_rx()
        rx.case_id = case
        case.action_complete_consultation()
        self.assertEqual(rx.state, 'issued')


@tagged('post_install', '-at_install', 'dental_rx_sale_order')
class TestPrescriptionSaleOrder(TransactionCase):
    """A prescription in a pharmacy branch becomes a sales order: stock is visible, never blocking."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.dental_has_pharmacy = True
        common = {'company_id': cls.company.id, 'company_ids': [cls.company.id]}
        cls.dentist_user = new_test_user(cls.env, login='rx_so_dentist', groups='base.group_user,dental_base.group_dental_dentist', **common)
        cls.pharmacist_user = new_test_user(cls.env, login='rx_so_pharmacist',
                                            groups='base.group_user,dental_pharmacy.group_dental_pharmacist', **common)
        cls.doctor = cls.env['hr.employee'].create({'name': 'Dr. SO', 'dental_role': 'dentist', 'user_id': cls.dentist_user.id})
        cls.patient = cls.env['res.partner'].create({'name': 'SO Patient', 'is_dental_patient': True, 'phone': '9000000066'})
        cls.medicine = cls.env['product.product'].create({
            'name': 'SO Amoxicillin 500', 'is_medicine': True, 'is_storable': True, 'list_price': 12.0})
        cls.stock_location = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1).lot_stock_id

    def _confirmed_rx(self, qty=10):
        rx = self.env['dental.prescription'].with_user(self.dentist_user).create({
            'patient_id': self.patient.id,
            'dentist_id': self.doctor.id,
            'line_ids': [(0, 0, {'medicine_id': self.medicine.id, 'quantity': qty})],
        })
        rx.action_confirm()
        return rx

    def test_out_of_stock_medicine_is_prescribed_with_quotation(self):
        # No stock at all: prescribing and confirming still work, a quotation is created
        rx = self._confirmed_rx()
        self.assertEqual(rx.line_ids.stock_alert, 'out')
        order = rx.sudo().sale_order_id
        self.assertTrue(order)
        self.assertEqual(order.state, 'draft', "Nothing is confirmed or reserved at prescription time")
        self.assertEqual(order.partner_id, self.patient)
        self.assertEqual(order.order_line.product_uom_qty, 10)
        self.assertEqual(order.order_line.dental_prescription_line_id, rx.line_ids)
        self.assertFalse(order.picking_ids)

    def test_dispense_confirms_order_without_second_delivery(self):
        lot = self.env['stock.lot'].create({'name': 'SO-LOT-1', 'product_id': self.medicine.id, 'company_id': self.company.id})
        self.env['stock.quant']._update_available_quantity(self.medicine, self.stock_location, 50, lot_id=lot)
        rx = self._confirmed_rx(qty=10)
        order = rx.sudo().sale_order_id
        action = rx.with_user(self.pharmacist_user).action_dispense()
        dispense = self.env['dental.pharmacy.dispense'].browse(action['res_id']).with_user(self.pharmacist_user)
        dispense.location_id = self.stock_location
        dispense.line_ids.write({'qty_to_dispense': 6, 'lot_id': lot.id})
        dispense.action_dispense()
        self.assertEqual(order.state, 'sale')
        self.assertEqual(order.order_line.qty_delivered, 6, "Delivered qty follows the pharmacy dispense")
        self.assertEqual(order.picking_ids, dispense.picking_id, "The dispense transfer is the only delivery")
        self.assertEqual(dispense.picking_id.state, 'done')
        self.assertEqual(self.medicine.with_context(location=self.stock_location.id).qty_available, 44, "Stock really goes down")
        dispense.action_create_invoice()
        self.assertEqual(order.order_line.qty_invoiced, 6)
        self.assertIn(dispense.invoice_id, order.invoice_ids)
        # Manager-approved return puts the stock back and lowers the delivered quantity
        manager = new_test_user(self.env, login='rx_so_manager', groups='base.group_user,dental_base.group_dental_manager',
                                company_id=self.company.id, company_ids=[self.company.id])
        dispense = dispense.with_user(manager)
        dispense.return_reason = 'Wrong strength'
        dispense.action_return()
        self.assertEqual(dispense.return_picking_id.state, 'done')
        self.assertEqual(self.medicine.with_context(location=self.stock_location.id).qty_available, 50)
        self.assertEqual(order.order_line.qty_delivered, 0)

    def test_issue_to_patient_cancels_quotation(self):
        rx = self._confirmed_rx()
        order = rx.sudo().sale_order_id
        rx.action_issue_to_patient()
        self.assertEqual(order.state, 'cancel')

    def test_cancel_and_reset_cancel_quotation(self):
        rx = self._confirmed_rx()
        first = rx.sudo().sale_order_id
        rx.action_draft()
        self.assertEqual(first.state, 'cancel')
        rx.action_confirm()
        self.assertNotEqual(rx.sudo().sale_order_id, first, "Re-confirming creates a fresh quotation")
        rx.action_cancel()
        self.assertEqual(rx.sudo().sale_order_id.state, 'cancel')
