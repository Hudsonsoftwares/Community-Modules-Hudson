import json
from datetime import date, timedelta

from odoo.tests import TransactionCase, tagged

from odoo.addons.abdm_base.tools import fidelius


def references(data):
    """Every 'reference' value found in a FHIR structure."""
    found = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key == 'reference':
                found.append(value)
            else:
                found += references(value)
    elif isinstance(data, list):
        for item in data:
            found += references(item)
    return found


def has_empty(data):
    if isinstance(data, dict):
        return any(v in (None, '', [], {}) or has_empty(v) for v in data.values())
    if isinstance(data, list):
        return any(v in (None, '', [], {}) or has_empty(v) for v in data)
    return False


@tagged('post_install', '-at_install', 'abdm')
class TestDentalFhir(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.company.write({'abdm_hip_id': 'IN2710000001', 'abdm_hip_name': 'Test Dental Clinic'})
        cls.patient = cls.env['res.partner'].create({
            'name': 'Ravi Kumar', 'is_dental_patient': True, 'gender': 'male',
            'date_of_birth': date(1990, 5, 17), 'phone': '9876543210',
            'abha_number': '91-1111-2222-3333', 'abha_address': 'ravi@sbx',
            'allergy_status': 'known', 'allergies': '<p>Penicillin, Latex</p>',
        })
        cls.dentist = cls.env['hr.employee'].create({
            'name': 'Dr. Asha Menon', 'dental_role': 'dentist', 'registration_number': 'KDC-12345'})
        cls.case = cls.env['dental.case'].create({
            'patient_id': cls.patient.id, 'chief_complaint': 'Pain in lower left tooth',
            'doctor_id': cls.dentist.id})
        cls.exam = cls.env['dental.clinical.examination'].create({
            'patient_id': cls.patient.id, 'case_id': cls.case.id, 'doctor_id': cls.dentist.id,
            'chief_complaint': 'Pain in lower left tooth', 'oral_hygiene': 'fair',
            'recommended_treatment': 'Root canal treatment on 36',
        })
        diagnosis = cls.env['dental.diagnosis'].create({'name': 'Irreversible pulpitis', 'code': 'K04.0'})
        cls.env['dental.patient.diagnosis'].create({
            'patient_id': cls.patient.id, 'case_id': cls.case.id, 'examination_id': cls.exam.id,
            'diagnosis_id': diagnosis.id, 'tooth_reference': '36'})
        cls.exam.write({'state': 'done'})
        medicine = cls.env['product.product'].create({'name': 'Amoxicillin', 'is_medicine': True})
        cls.rx = cls.env['dental.prescription'].create({
            'patient_id': cls.patient.id, 'dentist_id': cls.dentist.id, 'case_id': cls.case.id,
            'prescription_date': date.today(), 'diagnosis': 'Irreversible pulpitis 36',
            'line_ids': [(0, 0, {'medicine_id': medicine.id, 'dose': '1 tablet', 'route': 'oral',
                                 'frequency': 'tid', 'duration': 5, 'quantity': 15,
                                 'instructions': 'After food'})],
        })
        cls.rx.write({'state': 'issued'})

    def _check_bundle(self, bundle, profile):
        json.dumps(bundle)  # serializable
        self.assertEqual(bundle['resourceType'], 'Bundle')
        self.assertEqual(bundle['type'], 'document')
        composition = bundle['entry'][0]['resource']
        self.assertEqual(composition['resourceType'], 'Composition')
        self.assertTrue(composition['meta']['profile'][0].endswith(profile))
        full_urls = {e['fullUrl'] for e in bundle['entry']}
        for reference in references(bundle):
            self.assertIn(reference, full_urls, 'every reference must point inside the bundle')
        self.assertFalse(has_empty(bundle), 'FHIR forbids empty elements')
        return composition, {e['resource']['resourceType']: e['resource'] for e in bundle['entry']}

    def test_case_records(self):
        records = self.case._abdm_health_records()
        self.assertEqual(sorted(r['hi_type'] for r in records), ['OPConsultation', 'Prescription'])

        op = next(r for r in records if r['hi_type'] == 'OPConsultation')
        composition, by_type = self._check_bundle(op['bundle'], 'OPConsultRecord')
        self.assertEqual(op['reference'], self.exam.name)
        patient = by_type['Patient']
        self.assertEqual(patient['identifier'][0]['value'], '91-1111-2222-3333')
        self.assertEqual(patient['gender'], 'male')
        self.assertEqual(patient['birthDate'], '1990-05-17')
        self.assertEqual(by_type['Practitioner']['identifier'][0]['value'], 'KDC-12345')
        self.assertEqual(by_type['Organization']['identifier'][0]['value'], 'IN2710000001')
        titles = [s['title'] for s in composition['section']]
        for title in ('Chief complaints', 'Allergies', 'Medical history', 'Physical examination', 'Follow up'):
            self.assertIn(title, titles)
        conditions = [e['resource'] for e in op['bundle']['entry'] if e['resource']['resourceType'] == 'Condition']
        pulpitis = next(c for c in conditions if c['code'].get('text') == 'Irreversible pulpitis')
        self.assertEqual(pulpitis['code']['coding'][0]['code'], 'K04.0')
        self.assertEqual(pulpitis['bodySite'][0]['text'], 'Tooth 36')
        allergies = [e['resource']['code']['text'] for e in op['bundle']['entry']
                     if e['resource']['resourceType'] == 'AllergyIntolerance']
        self.assertEqual(sorted(allergies), ['Latex', 'Penicillin'])

        rx = next(r for r in records if r['hi_type'] == 'Prescription')
        composition, by_type = self._check_bundle(rx['bundle'], 'PrescriptionRecord')
        med = by_type['MedicationRequest']
        self.assertIn('Amoxicillin', med['medicationCodeableConcept']['text'])
        self.assertIn('Three times daily', med['dosageInstruction'][0]['text'])
        self.assertEqual(med['dosageInstruction'][0]['route']['text'], 'Oral')
        self.assertEqual(med['dosageInstruction'][0]['additionalInstruction'][0]['text'], 'After food')
        self.assertEqual(med['dosageInstruction'][0]['timing']['repeat']['boundsDuration']['value'], 5)

    def test_filters_and_drafts(self):
        self.assertEqual([r['hi_type'] for r in self.case._abdm_health_records(hi_types=['Prescription'])],
                         ['Prescription'])
        self.assertFalse(self.case._abdm_health_records(date_from=date.today() + timedelta(days=1)))
        draft_case = self.env['dental.case'].create({'patient_id': self.patient.id})
        self.env['dental.clinical.examination'].create({
            'patient_id': self.patient.id, 'case_id': draft_case.id, 'chief_complaint': 'x'})
        self.assertFalse(draft_case._abdm_health_records(), 'unsigned examinations are not shared')

    def test_encrypted_transfer_roundtrip(self):
        bundle = self.case._abdm_health_records()[0]['bundle']
        hip, hiu = fidelius.KeyMaterial(), fidelius.KeyMaterial()
        cipher = fidelius.encrypt(json.dumps(bundle), hip, hiu.public_key, hiu.nonce_b64)
        self.assertEqual(json.loads(fidelius.decrypt(cipher, hiu, hip.public_key, hip.nonce_b64)), bundle)

    def test_preview_action(self):
        action = self.case.action_abdm_preview_records()
        preview = self.env['abdm.fhir.preview'].browse(action['res_id'])
        self.assertIn('OPConsultation', preview.summary)
        self.assertIn('"resourceType": "Composition"', preview.content)
        server_action = self.env.ref('dental_abdm.action_server_dental_case_abdm_preview')
        self.assertEqual(server_action.binding_model_id.model, 'dental.case')
