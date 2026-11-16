import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from .common import AbdmTestMixin, FakeResponse


@tagged('post_install', '-at_install', 'abdm')
class TestAbdmGateway(AbdmTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_abdm()
        cls.gateway = cls.env['abdm.gateway']

    def test_missing_credentials(self):
        self.env['ir.config_parameter'].sudo().set_str('abdm_base.client_secret', '')
        self.fake_abdm()
        with self.assertRaises(UserError):
            self.gateway.test_connection()
        self.assertFalse(self.calls, "No call must be made without credentials")

    def test_login_headers_and_token_cache(self):
        self.fake_abdm({('GET', '/gateway/v3/bridge-services'): FakeResponse(200, [])})
        info = self.gateway.test_connection()
        self.assertEqual(info['environment'], 'sandbox')
        login = self.calls[0]
        self.assertEqual(login['url'], 'https://dev.abdm.gov.in/api/hiecm/gateway/v3/sessions')
        self.assertEqual(login['json']['grantType'], 'client_credentials')
        self.assertEqual(login['headers']['X-CM-ID'], 'sbx')
        self.assertTrue(login['headers']['REQUEST-ID'])
        self.assertTrue(login['headers']['TIMESTAMP'].endswith('Z'))

        # Two API calls reuse the cached token: no second login.
        self.gateway.get_bridge_services()
        self.gateway.get_bridge_services()
        logins = [c for c in self.calls if c['url'].endswith('/sessions')]
        self.assertEqual(len(logins), 1)
        self.assertEqual(self.calls[-1]['headers']['Authorization'], 'Bearer tok-1')

    def test_secret_never_logged(self):
        self.fake_abdm()
        self.gateway.test_connection()
        log = self.env['abdm.api.log'].search([('endpoint', '=', '/gateway/v3/sessions')], limit=1)
        self.assertTrue(log)
        self.assertNotIn('super-secret-value', log.request_body)
        self.assertNotIn('tok-1', log.response_body)
        self.assertIn('SBX_TEST', log.request_body)

    def test_wrong_credentials_message(self):
        self.fake_abdm({('POST', '/gateway/v3/sessions'): FakeResponse(
            400, {'error': {'code': 'ABDM-9999: ', 'message': 'Invalid user credentials'}})})
        # Not assertRaises: it rolls back the savepoint, and with it the log
        # line (in production the log has its own cursor and survives).
        try:
            self.gateway.test_connection()
        except UserError as exc:
            self.assertIn('Invalid user credentials', str(exc))
        else:
            self.fail('UserError expected')
        log = self.env['abdm.api.log'].search([('endpoint', '=', '/gateway/v3/sessions')], limit=1)
        self.assertEqual(log.state, 'error')
        self.assertEqual(log.status_code, 400)

    def test_expired_token_is_refreshed_once(self):
        self.fake_abdm({
            ('POST', '/gateway/v3/sessions'): [
                FakeResponse(200, {'accessToken': 'tok-1', 'expiresIn': 1200}),
                FakeResponse(200, {'accessToken': 'tok-2', 'expiresIn': 1200}),
            ],
            ('GET', '/gateway/v3/bridge-services'): [
                FakeResponse(401, {'code': '900901', 'message': 'Invalid Credentials'}),
                FakeResponse(200, [{'id': 'IN2710000001'}]),
            ],
        })
        data = self.gateway.get_bridge_services()
        self.assertEqual(data, [{'id': 'IN2710000001'}])
        self.assertEqual(self.calls[-1]['headers']['Authorization'], 'Bearer tok-2')

    def test_register_bridge_url(self):
        self.fake_abdm({('PATCH', '/gateway/v3/bridge/url'): FakeResponse(202)})
        self.gateway.register_bridge_url()
        self.assertEqual(self.calls[-1]['json'], {'url': 'https://clinic.example.com'})
        with self.assertRaises(UserError):
            self.gateway.register_bridge_url('http://insecure.example.com')

    def test_send_async_and_callback_match(self):
        self.fake_abdm({('POST', '/hip/test'): FakeResponse(202)})
        partner = self.env['res.partner'].create({'name': 'ABDM Patient'})
        tx = self.gateway._send_async('test.flow', '/hip/test', {'otp': '123456'}, record=partner)
        self.assertEqual(tx.state, 'sent')
        self.assertEqual(tx.res_model, 'res.partner')
        self.assertEqual(tx.res_id, partner.id)
        self.assertNotIn('123456', tx.request_summary)
        self.assertEqual(self.calls[-1]['headers']['REQUEST-ID'], tx.request_id)

        self.gateway._handle_callback('/api/v3/hip/on-test',
                                      {'status': 'OK', 'response': {'requestId': tx.request_id}}, {})
        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.response_data['status'], 'OK')

        tx2 = self.gateway._send_async('test.flow', '/hip/test', {})
        self.gateway._handle_callback('/api/v3/hip/on-test', {
            'error': {'code': 'ABDM-1001', 'message': 'Patient not found'},
            'response': {'requestId': tx2.request_id}}, {})
        self.assertEqual(tx2.state, 'error')
        self.assertIn('Patient not found', tx2.error_message)

    def test_callback_token_verification(self):
        self.fake_abdm()
        claims = self.gateway._verify_callback_token('Bearer ' + self.make_jwt())
        self.assertEqual(claims['iss'], 'gateway')

        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with self.assertRaises(ValueError):
            self.gateway._verify_callback_token('Bearer ' + self.make_jwt(key=other_key))
        with self.assertRaises(ValueError):
            self.gateway._verify_callback_token('Bearer ' + self.make_jwt(claims={'exp': 1000}))
        with self.assertRaises(ValueError):
            self.gateway._verify_callback_token('Bearer not-a-jwt')
        with self.assertRaises(ValueError):
            self.gateway._verify_callback_token(None)

    def test_abha_encrypt(self):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_b64 = base64.b64encode(private_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        self.fake_abdm({('GET', '/v3/profile/public/certificate'): FakeResponse(
            200, {'publicKey': public_b64, 'encryptionAlgorithm': 'RSA/ECB/OAEPWithSHA-1AndMGF1Padding'})})
        encrypted = self.gateway.abha_encrypt('123456')
        self.assertTrue(self.calls[-1]['url'].startswith('https://abhasbx.abdm.gov.in/abha/api'))
        plain = private_key.decrypt(base64.b64decode(encrypted), padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA1()), algorithm=hashes.SHA1(), label=None))
        self.assertEqual(plain, b'123456')

    def test_settings_buttons(self):
        self.fake_abdm({('PATCH', '/gateway/v3/bridge/url'): FakeResponse(202)})
        settings = self.env['res.config.settings'].create({
            'abdm_client_id': 'SBX_TEST',
            'abdm_client_secret': 'super-secret-value',
            'abdm_callback_url': 'https://clinic.example.com/',
            'abdm_hip_id': 'IN2710000001',
        })
        action = settings.action_abdm_test_connection()
        self.assertEqual(action['params']['type'], 'success')
        self.assertEqual(self.env.company.abdm_hip_id, 'IN2710000001')
        settings.action_abdm_register_bridge_url()
        self.assertEqual(self.calls[-1]['json'], {'url': 'https://clinic.example.com'})

    def test_cron_expire(self):
        tx = self.env['abdm.transaction'].create({'operation': 'x', 'request_id': 'r-old'})
        tx.sent_date = '2020-01-01 00:00:00'
        self.env['abdm.transaction']._cron_expire()
        self.assertEqual(tx.state, 'timeout')
