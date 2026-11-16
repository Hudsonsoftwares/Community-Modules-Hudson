import json
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.abdm_base.tests.common import AbdmTestMixin, FakeResponse
from odoo.addons.abdm_base.tools import fidelius

HIP_ID = 'IN2710000001'
PUSH_URL = 'https://hiu.example.com/data/push'


@tagged('post_install', '-at_install', 'abdm')
class TestHipFlows(AbdmTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_abdm()
        cls.env.company.write({'abdm_hip_id': HIP_ID, 'abdm_hip_name': 'Test Dental Clinic'})
        cls.patient = cls.env['res.partner'].create({
            'name': 'Ravi Kumar', 'is_dental_patient': True, 'gender': 'male',
            'date_of_birth': date(1990, 5, 17), 'phone': '9876543210',
            'abha_number': '91-1111-2222-3333', 'abha_address': 'ravi@sbx',
        })
        cls.dentist = cls.env['hr.employee'].create({'name': 'Dr. Asha', 'dental_role': 'dentist'})
        cls.case = cls._make_case('Tooth pain 36')
        cls.case2 = cls._make_case('Cleaning')
        cls.gw = cls.env['abdm.gateway']

    @classmethod
    def _make_case(cls, complaint):
        case = cls.env['dental.case'].create({
            'patient_id': cls.patient.id, 'chief_complaint': complaint, 'doctor_id': cls.dentist.id,
            'branch_id': cls.env.company.id})
        exam = cls.env['dental.clinical.examination'].create({
            'patient_id': cls.patient.id, 'case_id': case.id, 'chief_complaint': complaint})
        exam.write({'state': 'done'})
        return case

    def setUp(self):
        super().setUp()
        self.fake_abdm({
            ('POST', '/v3/token/generate-token'): FakeResponse(202),
            ('POST', '/hip/v3/link/carecontext'): FakeResponse(202),
            ('POST', '/hip/v3/link/context/notify'): FakeResponse(202),
            ('POST', '/care-context/on-discover'): FakeResponse(202),
            ('POST', '/link/care-context/on-init'): FakeResponse(202),
            ('POST', '/link/care-context/on-confirm'): FakeResponse(202),
            ('POST', '/consent/v3/request/hip/on-notify'): FakeResponse(202),
            ('POST', '/health-information/hip/on-request'): FakeResponse(202),
            ('POST', '/data-flow/v3/health-information/notify'): FakeResponse(202),
            ('POST', '/data/push'): FakeResponse(202),
        })

    def calls_to(self, suffix):
        return [c for c in self.calls if c['url'].endswith(suffix)]

    def callback(self, path, body, request_id='cb-req-1', hip_id=HIP_ID):
        return self.gw._handle_callback(path, body, {'Request-Id': request_id, 'X-Hip-Id': hip_id})

    # ------------------------------------------------------------------
    def test_clinic_initiated_linking(self):
        self.case.action_abdm_link()
        cc = self.case.abdm_care_context_id
        self.assertEqual(cc.state, 'linking')
        self.assertEqual(cc.reference, self.case.name)
        self.assertEqual(cc.hi_types, 'OPConsultation')
        token_call = self.calls_to('/v3/token/generate-token')[-1]
        self.assertEqual(token_call['headers']['X-HIP-ID'], HIP_ID)
        self.assertEqual(token_call['json'], {
            'abhaNumber': '91111122223333', 'abhaAddress': 'ravi@sbx', 'name': 'Ravi Kumar',
            'gender': 'M', 'yearOfBirth': 1990})

        tx = self.env['abdm.transaction'].search([('operation', '=', 'hip.link_token')], limit=1)
        self.callback('/api/v3/hip/token/on-generate-token', {
            'abhaAddress': 'ravi@sbx', 'linkToken': 'LINK-TOKEN-1', 'response': {'requestId': tx.request_id}})
        link_call = self.calls_to('/hip/v3/link/carecontext')[-1]
        self.assertEqual(link_call['headers']['X-LINK-TOKEN'], 'LINK-TOKEN-1')
        patient_block = link_call['json']['patient'][0]
        self.assertEqual(patient_block['referenceNumber'], self.patient.dental_patient_id)
        self.assertEqual(patient_block['hiType'], 'OPConsultation')
        self.assertEqual(patient_block['careContexts'][0]['referenceNumber'], self.case.name)
        self.assertEqual(patient_block['count'], 1)

        tx2 = self.env['abdm.transaction'].search([('operation', '=', 'hip.link_care_context')], limit=1)
        self.callback('/api/v3/link/on_carecontext', {
            'abhaAddress': 'ravi@sbx', 'status': 'Successfully Linked care context',
            'response': {'requestId': tx2.request_id}})
        self.assertEqual(cc.state, 'linked')
        self.assertEqual(cc.link_method, 'hip')

        # The token is reused for the next case: no new token request.
        before = len(self.calls_to('/v3/token/generate-token'))
        self.case2.action_abdm_link()
        self.assertEqual(len(self.calls_to('/v3/token/generate-token')), before)
        self.assertEqual(self.calls_to('/hip/v3/link/carecontext')[-1]['json']['patient'][0]
                         ['careContexts'][0]['referenceNumber'], self.case2.name)

        cc.action_notify_new_data()
        note = self.calls_to('/hip/v3/link/context/notify')[-1]['json']['notification']
        self.assertEqual(note['careContextReference'], self.case.name)
        self.assertEqual(note['hip']['id'], HIP_ID)

        with self.assertRaises(UserError):
            self.case.unlink()  # linked records are protected

    def test_link_errors(self):
        self.env.company.abdm_hip_id = False
        with self.assertRaisesRegex(UserError, 'HFR'):
            self.case.action_abdm_link()
        self.env.company.abdm_hip_id = HIP_ID
        self.patient.date_of_birth = False
        with self.assertRaisesRegex(UserError, 'year of birth'):
            self.case.action_abdm_link()
        self.patient.date_of_birth = date(1990, 5, 17)
        self.patient.write({'abha_number': False, 'abha_address': False})
        with self.assertRaisesRegex(UserError, 'no ABHA'):
            self.case.action_abdm_link()

    def test_token_error_marks_context(self):
        self.case.action_abdm_link()
        tx = self.env['abdm.transaction'].search([('operation', '=', 'hip.link_token')], limit=1)
        self.callback('/api/v3/hip/token/on-generate-token', {
            'error': {'code': 'ABDM-1100', 'message': 'Demographics mismatch'},
            'response': {'requestId': tx.request_id}})
        cc = self.case.abdm_care_context_id
        self.assertEqual(cc.state, 'error')
        self.assertIn('Demographics mismatch', cc.error_message)

    def test_patient_discovery_and_otp_linking(self):
        self.callback('/api/v3/hip/patient/care-context/discover', {
            'transactionId': 'txn-d1',
            'patient': {'id': 'someone@sbx', 'name': 'Ravi Kumar', 'gender': 'M', 'yearOfBirth': 1990,
                        'verifiedIdentifiers': [{'type': 'ABHA_NUMBER', 'value': '91-1111-2222-3333'}]},
        }, request_id='disc-1')
        reply = self.calls_to('/care-context/on-discover')[-1]['json']
        self.assertEqual(reply['response']['requestId'], 'disc-1')
        self.assertEqual(reply['matchedBy'], ['ABHA_NUMBER'])
        refs = sorted(c['referenceNumber'] for c in reply['patient'][0]['careContexts'])
        self.assertEqual(refs, sorted([self.case.name, self.case2.name]))

        self.callback('/api/v3/hip/link/care-context/init', {
            'transactionId': 'txn-d1', 'abhaAddress': 'ravi@sbx',
            'patient': [{'referenceNumber': self.patient.dental_patient_id, 'hiType': 'OPConsultation',
                         'count': 1, 'careContexts': [{'referenceNumber': self.case.name}]}],
        }, request_id='init-1')
        init_reply = self.calls_to('/link/care-context/on-init')[-1]['json']
        link_ref = init_reply['link']['referenceNumber']
        self.assertEqual(init_reply['link']['meta']['communicationMedium'], 'MOBILE')
        request = self.env['abdm.link.request'].search([('link_reference', '=', link_ref)])
        self.assertTrue(request.sandbox_otp, 'sandbox shows the OTP for testers')

        self.callback('/api/v3/hip/link/care-context/confirm', {
            'confirmation': {'linkRefNumber': link_ref, 'token': '000000' if request.sandbox_otp != '000000' else '111111'}})
        self.assertIn('error', self.calls_to('/link/care-context/on-confirm')[-1]['json'])
        self.assertEqual(self.case.abdm_care_context_id.state, 'not_linked')

        self.callback('/api/v3/hip/link/care-context/confirm', {
            'confirmation': {'linkRefNumber': link_ref, 'token': request.sandbox_otp}}, request_id='conf-2')
        confirm_reply = self.calls_to('/link/care-context/on-confirm')[-1]['json']
        self.assertEqual(confirm_reply['response']['requestId'], 'conf-2')
        self.assertEqual(confirm_reply['patient'][0]['careContexts'][0]['referenceNumber'], self.case.name)
        self.case.invalidate_recordset()
        self.assertEqual(self.case.abdm_care_context_id.state, 'linked')
        self.assertEqual(self.case.abdm_care_context_id.link_method, 'patient')
        self.assertFalse(request.sandbox_otp, 'OTP removed once used')

    def test_discovery_by_mobile_and_not_found(self):
        self.callback('/api/v3/hip/patient/care-context/discover', {
            'transactionId': 'txn-m', 'patient': {
                'id': 'ravi.new@sbx', 'name': 'Ravi K', 'gender': 'M', 'yearOfBirth': 1990,
                'verifiedIdentifiers': [{'type': 'MOBILE', 'value': '+91-9876543210'}]}})
        self.assertEqual(self.calls_to('/care-context/on-discover')[-1]['json']['matchedBy'], ['MOBILE'])
        self.callback('/api/v3/hip/patient/care-context/discover', {
            'transactionId': 'txn-x', 'patient': {
                'id': 'stranger@sbx', 'name': 'Nobody', 'gender': 'F', 'yearOfBirth': 2001,
                'verifiedIdentifiers': [{'type': 'MOBILE', 'value': '9000000000'}]}})
        reply = self.calls_to('/care-context/on-discover')[-1]['json']
        self.assertEqual(reply['error']['code'], 'ABDM-1010')

    def test_consent_and_encrypted_transfer(self):
        cc = self.case._abdm_ensure_care_context()
        cc._set_linked('hip')
        self.callback('/api/v3/consent/request/hip/notify', {'notification': {
            'status': 'GRANTED', 'consentId': 'consent-1',
            'consentDetail': {
                'consentId': 'consent-1', 'patient': {'id': 'ravi@sbx'},
                'purpose': {'text': 'Care Management', 'code': 'CAREMGT'},
                'hip': {'id': HIP_ID}, 'hiTypes': ['OPConsultation', 'Prescription'],
                'careContexts': [{'patientReference': self.patient.dental_patient_id,
                                  'careContextReference': self.case.name}],
                'permission': {'accessMode': 'VIEW',
                               'dateRange': {'from': '2020-01-01T00:00:00.000Z', 'to': '2030-01-01T00:00:00.000Z'},
                               'dataEraseAt': '2099-01-01T00:00:00.000Z'},
            }}}, request_id='consent-req')
        consent = self.env['abdm.consent'].search([('consent_id', '=', 'consent-1')])
        self.assertEqual(consent.status, 'GRANTED')
        self.assertEqual(consent.partner_id, self.patient)
        self.assertEqual(consent.care_context_ids, cc)
        ack = self.calls_to('/consent/v3/request/hip/on-notify')[-1]['json']
        self.assertEqual(ack['acknowledgement'], {'status': 'ok', 'consentId': 'consent-1'})
        self.assertEqual(ack['response']['requestId'], 'consent-req')

        hiu = fidelius.KeyMaterial()
        self.callback('/api/v3/hip/health-information/request', {
            'transactionId': 'txn-hi-1',
            'hiRequest': {'consent': {'id': 'consent-1'},
                          'dateRange': {'from': '2020-01-01T00:00:00.000Z', 'to': '2030-01-01T00:00:00.000Z'},
                          'dataPushUrl': PUSH_URL, 'keyMaterial': hiu.to_abdm()}})
        on_request = self.calls_to('/health-information/hip/on-request')[-1]['json']
        self.assertEqual(on_request['hiRequest']['sessionStatus'], 'ACKNOWLEDGED')

        push = self.calls_to('/data/push')[-1]
        self.assertNotIn('Authorization', push['headers'], 'no ABDM token to non-ABDM hosts')
        body = push['json']
        self.assertEqual(body['transactionId'], 'txn-hi-1')
        self.assertEqual(len(body['entries']), 1)
        entry = body['entries'][0]
        self.assertEqual(entry['careContextReference'], self.case.name)
        plain = fidelius.decrypt(entry['content'], hiu, body['keyMaterial']['dhPublicKey']['keyValue'],
                                 body['keyMaterial']['nonce'])
        bundle = json.loads(plain)
        self.assertEqual(bundle['resourceType'], 'Bundle')
        self.assertEqual(bundle['entry'][0]['resource']['resourceType'], 'Composition')

        notify = self.calls_to('/data-flow/v3/health-information/notify')[-1]['json']['notification']
        self.assertEqual(notify['statusNotification']['sessionStatus'], 'TRANSFERRED')
        self.assertEqual(notify['statusNotification']['statusResponses'][0]['hiStatus'], 'DELIVERED')
        transfer = self.env['abdm.data.transfer'].search([('transaction_id', '=', 'txn-hi-1')])
        self.assertEqual(transfer.state, 'transferred')
        self.assertEqual(transfer.record_count, 1)

        # Revoked consent: request refused, nothing pushed.
        self.callback('/api/v3/consent/request/hip/notify', {'notification': {
            'status': 'REVOKED', 'consentId': 'consent-1'}})
        self.assertEqual(consent.status, 'REVOKED')
        pushes = len(self.calls_to('/data/push'))
        self.callback('/api/v3/hip/health-information/request', {
            'transactionId': 'txn-hi-2',
            'hiRequest': {'consent': {'id': 'consent-1'}, 'dataPushUrl': PUSH_URL, 'keyMaterial': hiu.to_abdm()}})
        refused = self.calls_to('/health-information/hip/on-request')[-1]['json']
        self.assertEqual(refused['error']['code'], 'ABDM-1020')
        self.assertEqual(len(self.calls_to('/data/push')), pushes)
