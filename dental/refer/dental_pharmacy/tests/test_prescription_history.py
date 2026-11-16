# -*- coding: utf-8 -*-
from datetime import date

from odoo.tests.common import TransactionCase


class TestPrescriptionHistory(TransactionCase):
    """Prescriptions tab of the case: this case's prescriptions and the patient's earlier ones."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.patient = cls.env['res.partner'].create({'name': 'Rx History Patient', 'is_dental_patient': True})
        cls.other_patient = cls.env['res.partner'].create({'name': 'Other Rx Patient', 'is_dental_patient': True})
        # dentist_id is required; the test user has no dentist employee to default from
        cls.dentist = cls.env['hr.employee'].create({
            'name': 'Dr. Rx History', 'dental_role': 'dentist', 'registration_number': 'RX-HIST-1'})
        cls.medicine = cls.env['product.product'].create({
            'name': 'Ibuprofen Rx History',
            'is_medicine': True,
            'dosage_form': 'tablet',
            'strength': '400 mg',
            'list_price': 5.0,
        })
        cls.old_case = cls.env['dental.case'].create({'patient_id': cls.patient.id, 'chief_complaint': 'Old pain'})
        cls.case = cls.env['dental.case'].create({'patient_id': cls.patient.id, 'chief_complaint': 'New pain'})

    def _rx(self, patient, case, **vals):
        return self.env['dental.prescription'].create(dict({
            'patient_id': patient.id,
            'dentist_id': self.dentist.id,
            'case_id': case.id if case else False,
            'prescription_date': date.today(),
            'line_ids': [(0, 0, {
                'medicine_id': self.medicine.id, 'dose': '1 tab', 'frequency': 'tid',
                'duration': 3, 'quantity': 9.0, 'instructions': 'After meals',
            })],
        }, **vals))

    def test_previous_prescriptions_exclude_current_case(self):
        old_rx = self._rx(self.patient, self.old_case)
        loose_rx = self._rx(self.patient, False)
        current_rx = self._rx(self.patient, self.case)
        self._rx(self.other_patient, False)
        self.case.invalidate_recordset(['previous_prescription_ids', 'history_prescription_ids'])
        self.assertEqual(self.case.previous_prescription_ids, old_rx | loose_rx)
        self.assertEqual(self.case.history_prescription_ids, old_rx | loose_rx | current_rx)
        self.assertEqual(self.case.prescription_ids, current_rx)

    def test_medication_summary(self):
        rx = self._rx(self.patient, self.old_case)
        self.assertEqual(rx.medicine_count, 1)
        summary = rx.medication_summary
        self.assertIn('Ibuprofen Rx History', summary)
        self.assertIn('400 mg', summary)
        self.assertIn('1 tab', summary)
        self.assertIn('3 days', summary)
        self.assertIn('qty 9', summary)
        self.assertIn('(After meals)', summary)
        empty = self.env['dental.prescription'].create({'patient_id': self.patient.id, 'dentist_id': self.dentist.id})
        self.assertFalse(empty.medication_summary)
        self.assertEqual(rx.action_open_prescription()['res_id'], rx.id)
