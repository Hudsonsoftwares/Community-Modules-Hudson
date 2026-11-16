import base64
import json
import time
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from odoo.addons.abdm_base.models import abdm_gateway as gateway_module


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


class FakeResponse:
    def __init__(self, status_code=200, body=None, headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        if isinstance(body, bytes):
            self.content = body
        else:
            self.content = json.dumps(body).encode() if body is not None else b''
        self.text = self.content.decode(errors='replace')

    def json(self):
        if isinstance(self._body, bytes):
            raise ValueError('binary body')
        return self._body


class AbdmTestMixin:
    """Configures sandbox credentials and fakes ABDM over HTTP."""

    @classmethod
    def _setup_abdm(cls):
        ICP = cls.env['ir.config_parameter'].sudo()
        ICP.set_str('abdm_base.environment', 'sandbox')
        ICP.set_str('abdm_base.client_id', 'SBX_TEST')
        ICP.set_str('abdm_base.client_secret', 'super-secret-value')
        ICP.set_str('abdm_base.callback_url', 'https://clinic.example.com')
        cls.signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        numbers = cls.signing_key.public_key().public_numbers()
        cls.jwks = {'keys': [{
            'kty': 'RSA', 'kid': 'test-kid', 'alg': 'RS256', 'use': 'sig',
            'n': b64url(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, 'big')),
            'e': b64url(numbers.e.to_bytes(3, 'big')),
        }]}

    def setUp(self):
        super().setUp()
        with gateway_module._CACHE_LOCK:
            gateway_module._TOKEN_CACHE.clear()
            gateway_module._JWKS_CACHE.clear()
            gateway_module._ABHA_KEY_CACHE.clear()
        self.calls = []
        self.routes = {}

    def make_jwt(self, claims=None, key=None, kid='test-kid'):
        header = {'alg': 'RS256', 'typ': 'JWT', 'kid': kid}
        claims = claims or {'iss': 'gateway', 'exp': int(time.time()) + 600}
        signing_input = '%s.%s' % (b64url(json.dumps(header).encode()), b64url(json.dumps(claims).encode()))
        signature = (key or self.signing_key).sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
        return '%s.%s' % (signing_input, b64url(signature))

    def fake_abdm(self, routes=None):
        """Patch requests.request. ``routes`` maps (METHOD, path suffix) to a
        FakeResponse or a list of them (consumed in order)."""
        self.routes = dict(routes or {})
        self.routes.setdefault(('POST', '/gateway/v3/sessions'),
                               FakeResponse(200, {'accessToken': 'tok-1', 'expiresIn': 1200}))
        self.routes.setdefault(('GET', '/gateway/v3/certs'), FakeResponse(200, self.jwks))

        def fake_request(method, url, headers=None, data=None, timeout=None):
            try:
                body = json.loads(data) if data else None
            except ValueError:  # form-encoded bodies (e.g. token logins)
                body = None
            self.calls.append({'method': method, 'url': url, 'headers': headers,
                               'json': body, 'data': data})
            for (m, suffix), resp in self.routes.items():
                if m == method and url.endswith(suffix):
                    if isinstance(resp, list):
                        return resp.pop(0) if len(resp) > 1 else resp[0]
                    return resp
            return FakeResponse(404, {'error': {'code': 'TEST-404', 'message': 'no fake route'}})

        patcher = patch.object(gateway_module.requests, 'request', side_effect=fake_request)
        patcher.start()
        self.addCleanup(patcher.stop)
