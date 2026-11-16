import json
import uuid

from odoo import fields
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.abdm_base.tests.common import AbdmTestMixin, FakeResponse
from odoo.addons.abdm_nhcx import const
from odoo.addons.abdm_nhcx.tools import fhir_insurance, jwe

API_URL = 'https://nhcx.example.com/api/v1'


@tagged('post_install', '-at_install', 'abdm_nhcx')
class TestJwe(TransactionCase):

    def test_roundtrip_and_tampering(self):
        private_pem, cert_pem = jwe.generate_key_pair('HFR-1', organization='Clinic')
        public_key = jwe.load_public_key(cert_pem)
        private_key = jwe.load_private_key(private_pem)
        token = jwe.encrypt({'resourceType': 'Bundle', 'x': 'é'}, {const.H_SENDER: 'A'}, public_key)
        self.assertEqual(len(token.split('.')), 5)
        self.assertEqual(jwe.read_header(token)[const.H_SENDER], 'A')
        header, payload = jwe.decrypt(token, private_key)
        self.assertEqual(payload, {'resourceType': 'Bundle', 'x': 'é'})
        self.assertEqual((header['alg'], header['enc']), ('RSA-OAEP-256', 'A256GCM'))

        parts = token.split('.')
        parts[3] = jwe.b64url_encode(b'X' + jwe.b64url_decode(parts[3])[1:])
        with self.assertRaises(jwe.JweError):
            jwe.decrypt('.'.join(parts), private_key)
        other_private, _cert = jwe.generate_key_pair('OTHER')
        with self.assertRaises(jwe.JweError):
            jwe.decrypt(token, jwe.load_private_key(other_private))
        self.assertIn('CN=HFR-1', jwe.certificate_info(cert_pem)['subject'])


class NhcxCommon(AbdmTestMixin):

    @classmethod
    def _setup_nhcx(cls):
        cls._setup_abdm()
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_str('abdm_nhcx.api_url', API_URL)
        ICP.set_str('abdm_nhcx.auth_mode', 'abdm')
        cls.company = cls.env.company
        cls.company.write({'abdm_hip_id': 'IN2710000001', 'nhcx_participant_code': 'HFR-TEST-1'})
        cls.company._nhcx_generate_keys(overwrite=True)
        cls.payer_private_pem, payer_cert = jwe.generate_key_pair('PAYER-1')
        cls.insurer = cls.env['res.partner'].create({
            'name': 'Star Health (test)', 'is_company': True, 'insurance_partner_type': 'insurer',
            'insurance_connector': 'nhcx', 'nhcx_participant_code': 'PAYER-1',
            'nhcx_encryption_cert': payer_cert,
        })
        cls.plan = cls.env['insurance.plan'].create({'name': 'Family Floater', 'insurer_id': cls.insurer.id})
        cls.patient = cls.env['res.partner'].create({'name': 'Meera (test)', 'phone': '+919800000001'})
        cls.policy = cls.env['insurance.policy'].create({
            'partner_id': cls.patient.id, 'holder_id': cls.patient.id, 'plan_id': cls.plan.id,
            'member_id': 'MEM-001', 'policy_number': 'POL-77',
        })

    def send_check(self):
        self.fake_abdm({('POST', '/coverageeligibility/check'): FakeResponse(202, {
            'timestamp': 1, 'correlation_id': 'x', 'api_call_id': 'y'})})
        action = self.policy.action_check_eligibility()
        return self.env['insurance.eligibility'].browse(action['res_id'])

    def last_call(self, suffix):
        return [c for c in self.calls if c['url'].endswith(suffix)][-1]

    def payer_answer(self, check, bundle, status=const.STATUS_COMPLETE, sender='PAYER-1'):
        headers = {
            const.H_API_CALL_ID: str(uuid.uuid4()),
            const.H_CORRELATION_ID: check.external_ref,
            const.H_WORKFLOW_ID: str(uuid.uuid4()),
            const.H_SENDER: sender,
            const.H_RECIPIENT: 'HFR-TEST-1',
            const.H_TIMESTAMP: '2026-11-13T10:00:00.000Z',
            const.H_STATUS: status,
        }
        cert = self.company.nhcx_certificate
        return {'payload': jwe.encrypt(bundle, headers, jwe.load_public_key(cert))}

    @staticmethod
    def eligibility_response(inforce=True):
        return {
            'resourceType': 'Bundle', 'type': 'collection',
            'entry': [{'resource': {
                'resourceType': 'CoverageEligibilityResponse',
                'identifier': [{'value': 'STAR-RESP-9'}],
                'outcome': 'complete',
                'disposition': 'Policy active',
                'insurance': [{
                    'inforce': inforce,
                    'benefitPeriod': {'start': '2026-04-01', 'end': '2027-03-31'},
                    'item': [
                        {'category': {'text': 'Dental'}, 'name': 'Dental OPD',
                         'network': {'coding': [{'code': 'in'}]}, 'term': {'text': 'annual'},
                         'authorizationRequired': True,
                         'benefit': [{'type': {'text': 'benefit'},
                                      'allowedMoney': {'value': 15000, 'currency': 'INR'},
                                      'usedMoney': {'value': 4000, 'currency': 'INR'}}]},
                        {'category': {'text': 'Cosmetic'}, 'excluded': True},
                        {'name': 'Visits', 'benefit': [{'type': {'text': 'visit'},
                                                        'allowedUnsignedInt': 4, 'usedUnsignedInt': 1}]},
                    ],
                }],
            }}],
        }


@tagged('post_install', '-at_install', 'abdm_nhcx')
class TestNhcxEligibility(NhcxCommon, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_nhcx()

    def test_send_builds_encrypted_request(self):
        check = self.send_check()
        self.assertEqual(check.connector, 'nhcx')
        self.assertEqual(check.state, 'waiting', check.error_message)
        self.assertTrue(check.external_ref)
        call = self.last_call('/coverageeligibility/check')
        self.assertEqual(call['url'], API_URL + '/coverageeligibility/check')
        self.assertEqual(call['headers']['Authorization'], 'Bearer tok-1')   # ABDM session reused
        self.assertNotIn('X-CM-ID', call['headers'])
        header, bundle = jwe.decrypt(call['json']['payload'], jwe.load_private_key(self.payer_private_pem))
        self.assertEqual(header[const.H_SENDER], 'HFR-TEST-1')
        self.assertEqual(header[const.H_RECIPIENT], 'PAYER-1')
        self.assertEqual(header[const.H_CORRELATION_ID], check.external_ref)
        self.assertEqual(header[const.H_STATUS], const.STATUS_REQUEST)
        self.assertEqual(bundle['type'], 'collection')
        request = fhir_insurance.resources_of_type(bundle, 'CoverageEligibilityRequest')[0]
        self.assertEqual(request['purpose'], ['validation', 'benefits'])
        coverage = fhir_insurance.resources_of_type(bundle, 'Coverage')[0]
        self.assertEqual(coverage['subscriberId'], 'MEM-001')
        self.assertIn({'system': const.POLICY_SYSTEM, 'value': 'POL-77'}, coverage['identifier'])
        orgs = fhir_insurance.resources_of_type(bundle, 'Organization')
        self.assertEqual({o['name'] for o in orgs}, {'Star Health (test)', self.company.name})
        self.assertEqual(fhir_insurance.resources_of_type(bundle, 'Patient')[0]['name'][0]['text'], 'Meera (test)')
        tx = self.env['abdm.transaction'].search([('request_id', '=', check.external_ref)])
        self.assertEqual((tx.res_model, tx.res_id, tx.state), ('insurance.eligibility', check.id, 'sent'))

    def test_payer_answers_eligible(self):
        check = self.send_check()
        status, ack, error = self.env['nhcx.client'].handle_callback(
            'coverageeligibility/on_check', self.payer_answer(check, self.eligibility_response()))
        self.assertEqual((status, error), (202, None))
        self.assertEqual(ack['correlation_id'], check.external_ref)
        self.assertEqual(check.state, 'done')
        self.assertEqual(check.result, 'eligible')
        self.assertEqual(check.payer_reference, 'STAR-RESP-9')
        self.assertEqual(check.benefit_start, fields.Date.to_date('2026-04-01'))
        self.assertEqual(check.disposition, 'Policy active')
        dental, cosmetic, visits = check.benefit_line_ids.sorted('sequence')
        self.assertEqual((dental.allowed_amount, dental.used_amount, dental.remaining_amount),
                         (15000, 4000, 11000))
        self.assertEqual(dental.network, 'in')
        self.assertTrue(dental.requires_preauth)
        self.assertFalse(cosmetic.covered)
        self.assertEqual((visits.allowed_value, visits.used_value), ('4', '1'))
        self.assertEqual(self.policy.eligibility_status, 'eligible')
        self.assertTrue(self.policy.last_verified_date)
        tx = self.env['abdm.transaction'].search([('request_id', '=', check.external_ref)])
        self.assertEqual(tx.state, 'done')

    def test_payer_answers_not_in_force(self):
        check = self.send_check()
        self.env['nhcx.client'].handle_callback(
            'coverageeligibility/on_check', self.payer_answer(check, self.eligibility_response(False)))
        self.assertEqual((check.state, check.result), ('done', 'not_eligible'))
        self.assertEqual(self.policy.eligibility_status, 'not_eligible')

    def test_payer_error_plain_body(self):
        check = self.send_check()
        status, _ack, _error = self.env['nhcx.client'].handle_callback('coverageeligibility/on_check', {
            const.H_CORRELATION_ID: check.external_ref, const.H_SENDER: 'PAYER-1',
            const.H_STATUS: const.STATUS_ERROR,
            const.H_ERROR: {'code': 'ERR_INVALID_POLICY', 'message': 'Policy not found'},
        })
        self.assertEqual(status, 202)
        self.assertEqual(check.state, 'error')
        self.assertIn('Policy not found', check.error_message)

    def test_answer_from_wrong_sender_is_rejected(self):
        check = self.send_check()
        status, _ack, error = self.env['nhcx.client'].handle_callback(
            'coverageeligibility/on_check', self.payer_answer(check, self.eligibility_response(), sender='EVIL'))
        self.assertEqual(status, 403)
        self.assertIn('does not match', error)
        self.assertEqual(check.state, 'waiting')

    def test_unknown_correlation_is_acknowledged_and_ignored(self):
        status, _ack, error = self.env['nhcx.client'].handle_callback('coverageeligibility/on_check', {
            const.H_CORRELATION_ID: 'nope', const.H_SENDER: 'PAYER-1', const.H_STATUS: const.STATUS_COMPLETE})
        self.assertEqual(status, 202)
        self.assertIn('ignored', error)

    def test_exchange_refuses_request(self):
        self.fake_abdm({('POST', '/coverageeligibility/check'): FakeResponse(400, {
            const.H_ERROR: {'code': 'ERR_INVALID_PAYLOAD', 'message': 'bad bundle'}})})
        action = self.policy.action_check_eligibility()
        check = self.env['insurance.eligibility'].browse(action['res_id'])
        self.assertEqual(check.state, 'error')
        self.assertIn('bad bundle', check.error_message)

    def test_payer_without_code(self):
        self.insurer.nhcx_participant_code = False
        check = self.send_check()
        self.assertEqual(check.state, 'error')
        self.assertIn('participant code', check.error_message)
        self.assertFalse([c for c in self.calls if c['url'].endswith('/coverageeligibility/check')])

    def test_not_configured(self):
        self.env['ir.config_parameter'].sudo().set_str('abdm_nhcx.api_url', '')
        check = self.send_check()
        self.assertEqual(check.state, 'error')
        self.assertIn('NHCX API URL', check.error_message)

    def test_no_answer_times_out(self):
        check = self.send_check()
        tx = self.env['abdm.transaction'].search([('request_id', '=', check.external_ref)])
        tx.state = 'timeout'
        self.env['insurance.eligibility']._nhcx_expire(30)
        self.assertEqual(check.state, 'error')
        self.assertIn('No answer', check.error_message)

    def test_separate_token_login(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_str('abdm_nhcx.auth_mode', 'token')
        ICP.set_str('abdm_nhcx.token_url', 'https://nhcx.example.com/auth/token')
        ICP.set_str('abdm_nhcx.username', 'hfr-test-1@nhcx')
        ICP.set_str('abdm_nhcx.secret', 's3cret')
        self.fake_abdm({
            ('POST', '/auth/token'): FakeResponse(200, {'access_token': 'nhcx-tok', 'expires_in': 600}),
            ('POST', '/coverageeligibility/check'): FakeResponse(202, {}),
        })
        self.policy.action_check_eligibility()
        token_call = self.last_call('/auth/token')
        self.assertIsNone(token_call['json'])  # form-encoded, not JSON
        self.assertEqual(self.last_call('/coverageeligibility/check')['headers']['Authorization'], 'Bearer nhcx-tok')
        log = self.env['abdm.api.log'].search([('endpoint', '=', 'nhcx:token')], limit=1)
        self.assertNotIn('s3cret', log.request_body or '')

    def test_sync_payers(self):
        _key, cert = jwe.generate_key_pair('PAYER-2')
        self.fake_abdm({('POST', '/participant/search'): FakeResponse(200, {'participants': [
            {'participant_code': 'PAYER-2', 'participant_name': 'ICICI Lombard (test)', 'status': 'Active',
             'roles': ['payor'], 'encryption_cert': cert, 'primary_email': 'claims@example.com'},
        ]})})
        self.env['nhcx.client'].sync_payers()
        payer = self.env['res.partner'].search([('nhcx_participant_code', '=', 'PAYER-2')])
        self.assertEqual(payer.name, 'ICICI Lombard (test)')
        self.assertEqual((payer.insurance_partner_type, payer.insurance_connector), ('insurer', 'nhcx'))
        self.assertIn('BEGIN CERTIFICATE', payer.nhcx_encryption_cert)
        self.assertEqual(payer.nhcx_participant_status, 'Active')

    def test_keys_are_not_overwritten_silently(self):
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            self.company._nhcx_generate_keys()


@tagged('post_install', '-at_install', 'abdm_nhcx')
class TestNhcxCallbackRoute(NhcxCommon, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_nhcx()

    def test_route_acknowledges(self):
        response = self.url_open('/nhcx/coverageeligibility/on_check', data=json.dumps({
            const.H_CORRELATION_ID: 'unknown-id', const.H_SENDER: 'PAYER-1',
            const.H_STATUS: const.STATUS_COMPLETE,
        }), headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['correlation_id'], 'unknown-id')
        bad = self.url_open('/nhcx/coverageeligibility/on_check', data='not json',
                            headers={'Content-Type': 'application/json'})
        self.assertEqual(bad.status_code, 400)
