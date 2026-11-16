# -*- coding: utf-8 -*-
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import Form
from odoo.tests.common import TransactionCase


class TestCaseInlinePrescription(TransactionCase):
    """Prescribing directly on the case's Prescriptions tab, lines added like sales order lines."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.patient = cls.env['res.partner'].create({
            'name': 'Inline Rx Patient', 'is_dental_patient': True, 'email': 'inline.rx@example.com'})
        cls.dentist = cls.env['hr.employee'].create({
            'name': 'Dr. Inline Rx', 'dental_role': 'dentist', 'registration_number': 'RX-INLINE-1'})
        cls.medicine = cls.env['product.product'].create({
            'name': 'Amoxicillin Inline Test',
            'is_medicine': True,
            'dosage_form': 'capsule',
            'strength': '500 mg',
            'list_price': 2.0,
        })
        cls.case = cls.env['dental.case'].create({
            'patient_id': cls.patient.id,
            'doctor_id': cls.dentist.id,
            'chief_complaint': 'Swelling 46',
            'state': 'open',
        })

    def _prescribe_on_form(self):
        with Form(self.case) as case_form:
            case_form.rx_diagnosis = 'Periapical abscess 46'
            with case_form.rx_line_ids.new() as line:
                line.medicine_id = self.medicine
                line.frequency = 'tid'
                line.duration = 5
            case_form.rx_clinical_notes = 'Warm saline rinses'
        return self.case.current_prescription_id

    def test_lines_added_on_case_create_draft_prescription(self):
        self.assertFalse(self.case.current_prescription_id)
        rx = self._prescribe_on_form()
        self.assertTrue(rx, "Saving lines on the case creates the visit's draft prescription")
        self.assertEqual(rx.state, 'draft')
        self.assertEqual(rx.case_id, self.case)
        self.assertEqual(rx.patient_id, self.patient)
        self.assertEqual(rx.dentist_id, self.dentist)
        self.assertEqual(rx.diagnosis, 'Periapical abscess 46')
        self.assertEqual(rx.clinical_notes, 'Warm saline rinses')
        self.assertEqual(rx.line_ids.medicine_id, self.medicine)
        # Medicine onchange filled the dose and the quantity was computed: 1 capsule x 3/day x 5 days
        self.assertEqual(rx.line_ids.dose, '1 capsule')
        self.assertEqual(rx.line_ids.quantity, 15.0)

        # Editing again updates the same prescription instead of creating a second one
        with Form(self.case) as case_form:
            with case_form.rx_line_ids.edit(0) as line:
                line.duration = 3
        self.assertEqual(self.case.current_prescription_id, rx)
        self.assertEqual(rx.line_ids.quantity, 9.0)
        self.assertEqual(len(self.case.prescription_ids), 1)

    def test_saving_case_without_rx_creates_nothing(self):
        with Form(self.case) as case_form:
            case_form.clinical_notes = 'Reviewed'
        self.assertFalse(self.case.prescription_ids)

    def test_finalize_to_pharmacy(self):
        self.company.dental_has_pharmacy = True
        rx = self._prescribe_on_form()
        self.case.action_rx_finalize()
        self.assertEqual(rx.state, 'confirmed')
        self.assertTrue(rx.sale_order_id, 'The pharmacy gets a sales order for the medicines')
        self.assertEqual(rx.sale_order_id.order_line.product_id, self.medicine)
        self.assertFalse(self.case.current_prescription_id, 'A new prescription can be started afterwards')

    def test_finalize_without_pharmacy_emails_patient(self):
        self.company.dental_has_pharmacy = False
        rx = self._prescribe_on_form()
        self.case.action_rx_finalize()
        self.assertEqual(rx.state, 'issued')
        self.assertEqual(rx.fulfillment, 'patient')
        sent = rx.message_ids.filtered(lambda m: self.patient in m.partner_ids)
        self.assertTrue(sent, 'The prescription is emailed to the patient')
        self.assertTrue(sent.attachment_ids, 'The email carries the prescription PDF')

    def test_finalize_requires_medicines(self):
        with self.assertRaises(UserError):
            self.case.action_rx_finalize()

    def test_regimen_adds_its_medicines(self):
        template = self.env['dental.prescription.template'].create({
            'name': 'Post-extraction test regimen',
            'indication': 'Post-extraction pain',
            'line_ids': [Command.create({
                'medicine_id': self.medicine.id, 'dose': '1 capsule', 'route': 'oral',
                'frequency': 'bid', 'duration': 3, 'quantity': 6.0, 'instructions': 'After meals'})],
        })
        with Form(self.case) as case_form:
            case_form.rx_template_id = template
            self.assertEqual(len(case_form.rx_line_ids), 1)
            self.assertFalse(case_form.rx_template_id)
        rx = self.case.current_prescription_id
        self.assertEqual(rx.line_ids.quantity, 6.0)
        self.assertEqual(rx.diagnosis, 'Post-extraction pain')

    def test_stock_figures_for_forecast(self):
        rx = self._prescribe_on_form()
        line = rx.line_ids
        self.assertTrue(self.medicine.is_storable)
        self.assertEqual(line.stock_alert, 'out')
        self.assertEqual(line.stock_on_hand, 0.0)
        self.assertTrue(line.stock_warehouse_id)
        # Receive stock in the branch pharmacy: the forecast figures follow
        location = line.stock_warehouse_id.lot_stock_id
        self.env['stock.quant']._update_available_quantity(self.medicine, location, 100.0)
        self.env.invalidate_all()
        self.assertEqual(line.stock_on_hand, 100.0)
        self.assertEqual(line.stock_free_qty, 100.0)
        self.assertEqual(line.stock_forecast_qty, 100.0)
        self.assertIn(line.stock_alert, ('ok', 'low'))
