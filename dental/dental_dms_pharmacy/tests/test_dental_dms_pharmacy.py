# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, new_test_user, tagged

PDF = b'%PDF-1.4\n%%EOF'


@tagged('post_install', '-at_install', 'dental_dms')
class TestDentalDmsPharmacy(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['dms.folder.rule'].sudo().search([('model_name', '=', 'hr.employee')]).write({'active': False})
        cls.patient = cls.env['res.partner'].create({'name': 'Rx DMS Patient', 'is_dental_patient': True})
        cls.doctor = cls.env['hr.employee'].create({'name': 'Dr. Rx DMS', 'dental_role': 'dentist'})
        cls.case = cls.env['dental.case'].create({'patient_id': cls.patient.id, 'doctor_id': cls.doctor.id,
                                                  'chief_complaint': 'Pain'})
        medicine = cls.env['product.product'].create({'name': 'Amoxicillin DMS Test', 'is_medicine': True})
        cls.rx = cls.env['dental.prescription'].create({
            'patient_id': cls.patient.id, 'dentist_id': cls.doctor.id, 'case_id': cls.case.id,
            'line_ids': [(0, 0, {'medicine_id': medicine.id, 'quantity': 10})]})
        cls.pharmacist = new_test_user(cls.env, login='dms_pharmacist',
                                       groups='base.group_user,dental_pharmacy.group_dental_pharmacist')
        cls.receptionist = new_test_user(cls.env, login='dms_rx_reception',
                                         groups='base.group_user,dental_base.group_dental_receptionist')

    def test_prescription_document_filed_and_visible_to_pharmacy(self):
        att = self.env['ir.attachment'].create({'name': 'Rx scan.pdf', 'raw': PDF,
                                                'res_model': 'dental.prescription', 'res_id': self.rx.id})
        dms_file = self.env['dms.file'].sudo().search([('attachment_id', '=', att.id)])
        self.assertEqual(dms_file.dental_doc_type, 'prescription')
        self.assertEqual(dms_file.dental_patient_id, self.patient)
        self.assertFalse(dms_file.dental_case_id, 'no case link, so pharmacy staff are not blocked by case privacy')
        DmsFile = self.env['dms.file']
        self.assertIn(dms_file, DmsFile.with_user(self.pharmacist).search([]))
        DmsFile.with_user(self.pharmacist).browse(dms_file.id).check_access('read')
        self.assertNotIn(dms_file, DmsFile.with_user(self.receptionist).search([]),
                         'front desk has no permission on the Prescriptions folder')
        # still listed under the case's documents
        self.assertIn(dms_file, DmsFile.search(self.case._dental_dms_document_domain()))
        self.assertEqual(self.rx.dental_document_count, 1)
