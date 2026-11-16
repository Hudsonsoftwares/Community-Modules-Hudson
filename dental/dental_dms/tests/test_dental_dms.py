# -*- coding: utf-8 -*-
import base64
from datetime import datetime, timedelta

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged

PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF'


@tagged('post_install', '-at_install', 'dental_dms')
class TestDentalDms(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'DMS Branch B'})
        cls.patient = cls.env['res.partner'].create({'name': 'DMS Patient', 'is_dental_patient': True, 'phone': '9000000911'})
        cls.contact = cls.env['res.partner'].create({'name': 'Plain Supplier'})
        common = {'company_id': cls.company_a.id, 'company_ids': [cls.company_a.id]}
        cls.dentist_a = new_test_user(cls.env, login='dms_dentist_a', groups='base.group_user,dental_base.group_dental_dentist', **common)
        cls.dentist_a2 = new_test_user(cls.env, login='dms_dentist_a2', groups='base.group_user,dental_base.group_dental_dentist', **common)
        cls.reception_a = new_test_user(cls.env, login='dms_reception_a', groups='base.group_user,dental_base.group_dental_receptionist', **common)
        cls.manager_a = new_test_user(cls.env, login='dms_manager_a', groups='base.group_user,dental_base.group_dental_manager', **common)
        cls.manager_b = new_test_user(cls.env, login='dms_manager_b', groups='base.group_user,dental_base.group_dental_manager',
                                      company_id=cls.company_b.id, company_ids=[cls.company_b.id])
        # Pre-existing dms_enterprise_features issue (not part of this module): the "Route Employee
        # Documents" folder rule and hr.employee's own DMS folder set-up both create Employees/<name>,
        # so creating an employee fails while that rule is active. Disabled for the test transaction only.
        cls.env['dms.folder.rule'].sudo().search([('model_name', '=', 'hr.employee')]).write({'active': False})
        cls.doctor_a = cls.env['hr.employee'].create({'name': 'Dr. DMS A', 'dental_role': 'dentist',
                                                      'company_id': cls.company_a.id})
        cls.doctor_a.user_id = cls.dentist_a
        cls.doctor_a2 = cls.env['hr.employee'].create({'name': 'Dr. DMS A2', 'dental_role': 'dentist',
                                                       'company_id': cls.company_a.id})
        cls.doctor_a2.user_id = cls.dentist_a2
        start = datetime.now().replace(hour=4, minute=0, second=0, microsecond=0) + timedelta(days=5)
        cls.appointment = cls.env['dental.appointment'].create({
            'patient_id': cls.patient.id, 'doctor_id': cls.doctor_a.id, 'branch_id': cls.company_a.id,
            'date_start': start, 'date_end': start + timedelta(minutes=30), 'state': 'confirmed'})
        cls.case = cls.env['dental.case'].create({'patient_id': cls.patient.id, 'doctor_id': cls.doctor_a.id,
                                                  'appointment_id': cls.appointment.id, 'chief_complaint': 'Pain'})
        cls.plan = cls.env['dental.treatment.plan'].create({
            'patient_id': cls.patient.id, 'case_id': cls.case.id,
            'line_ids': [(0, 0, {'treatment_id': cls.env.ref('dental_catalog.treatment_crown').id, 'unit_price': 100})]})

    def _attach(self, record, name, raw, env=None):
        env = env or self.env
        return env['ir.attachment'].create({'name': name, 'raw': raw, 'res_model': record._name, 'res_id': record.id})

    def _dms(self, attachment):
        return self.env['dms.file'].sudo().search([('attachment_id', '=', attachment.id)])

    # ------------------------------------------------------------------ routing
    def test_case_attachment_is_filed_without_copy(self):
        att = self._attach(self.case, 'OPG panoramic.png', PNG)
        dms_file = self._dms(att)
        self.assertEqual(len(dms_file), 1)
        self.assertEqual(dms_file.attachment_id, att, 'DMS must reference the original attachment')
        self.assertFalse(dms_file.content_binary, 'content must not be duplicated in the database')
        # DMS Enterprise's initial revision may write the content back on the file: the filestore is
        # content-addressed, so it must point to the very same physical file as the original attachment.
        stored = self.env['ir.attachment'].sudo().search([('res_model', '=', 'dms.file'), ('res_id', '=', dms_file.id),
                                                          ('res_field', '=', 'content_file')])
        if stored:
            self.assertEqual(stored.store_fname, att.store_fname, 'no physical copy of the file')
        self.assertEqual(dms_file.dental_doc_type, 'imaging')
        self.assertEqual(dms_file.dental_patient_id, self.patient)
        self.assertEqual(dms_file.dental_case_id, self.case)
        self.assertEqual(dms_file.dental_appointment_id, self.appointment)
        self.assertEqual(dms_file.company_id, self.company_a)
        self.assertEqual(dms_file.directory_id.dental_patient_id, self.patient)
        self.assertEqual(dms_file.directory_id.parent_id.dental_doc_type, 'imaging')
        self.assertEqual(base64.b64decode(base64.b64encode(dms_file.content.content
                                          if hasattr(dms_file.content, 'content') else dms_file.content)), PNG)

    def test_plan_pdf_and_consent_routing(self):
        report = self._attach(self.plan, 'Estimate.pdf', PDF)
        consent = self._attach(self.plan, 'Signed consent crown.pdf', PDF + b' ')
        self.assertEqual(self._dms(report).dental_doc_type, 'treatment')
        self.assertEqual(self._dms(consent).dental_doc_type, 'consent')
        self.assertEqual(self._dms(consent).dental_treatment_plan_id, self.plan)
        self.assertEqual(self.plan.dental_consent_count, 1)
        self.assertEqual(self.patient.dental_document_count, 2)

    def test_same_name_gets_unique_file_name(self):
        first = self._dms(self._attach(self.case, 'report.pdf', PDF))
        second = self._dms(self._attach(self.case, 'report.pdf', PDF + b'2'))
        self.assertEqual(first.directory_id, second.directory_id)
        self.assertNotEqual(first.name, second.name)

    def test_non_patient_contact_not_filed(self):
        att = self._attach(self.contact, 'brochure.pdf', PDF)
        self.assertFalse(self._dms(att))

    def test_patient_document_filed_once(self):
        doc = self.env['dental.patient.document'].create({
            'patient_id': self.patient.id, 'name': 'Old IOPA', 'document_type': 'xray',
            'file': base64.b64encode(PNG).decode(), 'file_name': 'iopa.png'})
        files = self.env['dms.file'].sudo().search([('dental_patient_id', '=', self.patient.id)])
        self.assertEqual(len(files), 1, 'the mirror copy pushed on the patient must not be filed twice')
        self.assertEqual(files.dental_source_ref, doc)
        self.assertEqual(files.dental_doc_type, 'imaging')

    def test_existing_dms_file_is_enriched(self):
        """An attachment already filed by a DMS folder rule only receives the dental links."""
        rule_dir = self.env['dms.directory'].sudo().create({'name': 'Rule Target', 'company_id': self.company_a.id})
        self.env['dms.folder.rule'].sudo().create({
            'name': 'Route cases', 'model_id': self.env['ir.model']._get('dental.case').id,
            'directory_id': rule_dir.id, 'company_id': self.company_a.id})
        att = self._attach(self.case, 'routed.pdf', PDF)
        files = self._dms(att)
        self.assertEqual(len(files), 1)
        self.assertEqual(files.directory_id, rule_dir)
        self.assertEqual(files.dental_patient_id, self.patient)

    def test_wizard_upload(self):
        wizard = self.env['dental.dms.upload.wizard'].with_user(self.dentist_a).create({
            'res_model': 'dental.case', 'res_id': self.case.id, 'doc_type': 'clinical',
            'file': base64.b64encode(PDF).decode(), 'file_name': 'referral.pdf', 'name': 'Referral letter',
            'tooth_reference': '36'})
        wizard.action_upload()
        dms_file = self.env['dms.file'].sudo().search([('dental_case_id', '=', self.case.id)])
        self.assertEqual(dms_file.name, 'Referral letter.pdf')
        self.assertEqual(dms_file.dental_tooth_reference, '36')
        self.assertEqual(dms_file.create_uid, self.dentist_a)

    def test_odontogram_snapshot(self):
        self.case.action_dental_snapshot_odontogram()
        dms_file = self.env['dms.file'].sudo().search([('dental_case_id', '=', self.case.id),
                                                       ('dental_doc_type', '=', 'odontogram')])
        self.assertEqual(len(dms_file), 1)

    def test_routing_failure_never_blocks(self):
        Service = self.env['dental.dms.service']
        original = type(Service)._route_attachment_unsafe

        def boom(self_, *args, **kwargs):
            raise ValueError('boom')
        type(Service)._route_attachment_unsafe = boom
        try:
            att = self._attach(self.case, 'x.pdf', PDF)
        finally:
            type(Service)._route_attachment_unsafe = original
        self.assertTrue(att.exists())

    # ------------------------------------------------------------------ security
    def test_role_and_privacy_access(self):
        clinical = self._dms(self._attach(self.case, 'exam notes.pdf', PDF))
        DmsFile = self.env['dms.file']
        # treating dentist: clinical folder + case access
        self.assertIn(clinical, DmsFile.with_user(self.dentist_a).search([('dental_patient_id', '=', self.patient.id)]))
        # another dentist cannot read this case (dental_core rule) -> cannot read its documents either
        self.assertNotIn(clinical, DmsFile.with_user(self.dentist_a2).search([]))
        as_other = self.env['dms.file'].with_user(self.dentist_a2).browse(clinical.id)
        with self.assertRaises(AccessError):
            as_other.check_access('read')      # used by /web/content downloads
        with self.assertRaises(AccessError):
            as_other.check_access('write')
        self.assertFalse(as_other._filtered_access('read'))
        self.env.invalidate_all()
        with self.assertRaises(AccessError):
            as_other.read(['name'])
        # download through the standard binary controller helper
        with self.assertRaises(AccessError):
            self.env['ir.binary'].with_user(self.dentist_a2)._find_record(res_model='dms.file', res_id=clinical.id)
        self.env['dms.file'].with_user(self.dentist_a).browse(clinical.id).check_access('read')
        # front desk has no permission on the clinical folder
        self.assertNotIn(clinical, DmsFile.with_user(self.reception_a).search([]))
        # manager of the branch sees it; manager of another branch does not
        self.assertIn(clinical, DmsFile.with_user(self.manager_a).search([]))
        self.assertNotIn(clinical, DmsFile.with_user(self.manager_b).with_company(self.company_b).search([]))

    def test_frontdesk_sees_patient_records(self):
        record = self._dms(self._attach(self.patient, 'Insurance card.pdf', PDF))
        self.assertEqual(record.dental_doc_type, 'patient')
        self.assertIn(record, self.env['dms.file'].with_user(self.reception_a).search([]))
        self.assertEqual(self.patient.with_user(self.reception_a).dental_document_count, 1)

    def test_direct_dms_upload_inherits_folder_links(self):
        """A file uploaded straight in the DMS into a patient's folder gets the patient and type."""
        self._attach(self.case, 'first.png', PNG)        # creates X-Rays & Imaging / <patient>
        folder = self.env['dms.directory'].sudo().search([('dental_patient_id', '=', self.patient.id),
                                                          ('dental_doc_type', '=', 'imaging')])
        uploaded = self.env['dms.file'].sudo().create({'name': 'cbct.png', 'directory_id': folder.id,
                                                       'content': base64.b64encode(PNG).decode()})
        self.assertEqual(uploaded.dental_patient_id, self.patient)
        self.assertEqual(uploaded.dental_doc_type, 'imaging')
        self.assertIn(uploaded, self.env['dms.file'].search(self.patient._dental_dms_document_domain()))

    def test_smart_button_actions(self):
        self._attach(self.case, 'a.pdf', PDF)
        action = self.case.action_dental_documents()
        self.assertEqual(action['res_model'], 'dms.file')
        self.assertEqual(self.env['dms.file'].search_count(action['domain']), 1)
        wizard_action = self.patient.action_dental_add_document()
        self.assertEqual(wizard_action['context']['default_doc_type'], 'patient')
