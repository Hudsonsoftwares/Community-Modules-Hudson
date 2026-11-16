import json

from odoo.tests import HttpCase, tagged

from .common import AbdmTestMixin, FakeResponse


@tagged('post_install', '-at_install', 'abdm')
class TestAbdmCallback(AbdmTestMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_abdm()

    def _post(self, path, body, token=None):
        headers = {'Content-Type': 'application/json', 'REQUEST-ID': 'cb-1', 'X-CM-ID': 'sbx'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        return self.url_open(path, data=json.dumps(body), headers=headers)

    def test_signed_callback_completes_transaction(self):
        self.fake_abdm({('POST', '/hip/test'): FakeResponse(202)})
        tx = self.env['abdm.gateway']._send_async('test.flow', '/hip/test', {})
        body = {'status': 'SUCCESS', 'response': {'requestId': tx.request_id}}
        response = self._post('/api/v3/hip/on-test', body, token=self.make_jwt())
        self.assertEqual(response.status_code, 202)
        tx.invalidate_recordset()
        self.assertEqual(tx.state, 'done')
        self.assertEqual(tx.callback_path, '/api/v3/hip/on-test')
        log = self.env['abdm.api.log'].search([('direction', '=', 'incoming')], limit=1)
        self.assertEqual(log.correlation_id, tx.request_id)
        self.assertEqual(log.status_code, 202)

    def test_unsigned_callback_rejected(self):
        self.fake_abdm()
        response = self._post('/api/v3/hip/on-test', {'response': {'requestId': 'x'}})
        self.assertEqual(response.status_code, 401)
        log = self.env['abdm.api.log'].search([('direction', '=', 'incoming')], limit=1)
        self.assertEqual(log.state, 'error')

    def test_invalid_json(self):
        self.fake_abdm()
        response = self.url_open('/api/v3/hip/on-test', data='not json',
                                 headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 400)

    def test_verification_can_be_disabled(self):
        self.env['ir.config_parameter'].sudo().set_bool('abdm_base.verify_callbacks', False)
        self.fake_abdm()
        response = self._post('/api/v3/anything/else', {'hello': 'world'})
        self.assertEqual(response.status_code, 202)
