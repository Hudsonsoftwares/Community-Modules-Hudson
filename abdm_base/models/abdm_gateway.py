import base64
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature

from odoo import api, models
from odoo.exceptions import UserError

from .. import const

_logger = logging.getLogger(__name__)

# Process-wide caches, keyed per database + environment + client so several
# databases served by the same Odoo process never share a token.
_CACHE_LOCK = threading.Lock()
_TOKEN_CACHE = {}       # key -> (access_token, expires_at)
_JWKS_CACHE = {}        # key -> (jwks dict, fetched_at)
_ABHA_KEY_CACHE = {}    # key -> (public key object, fetched_at)
JWKS_TTL = 3600
ABHA_KEY_TTL = 6 * 3600


def _b64url_decode(value):
    value += '=' * (-len(value) % 4)
    return base64.urlsafe_b64decode(value.encode())


class AbdmError(UserError):
    """ABDM answered with an error, or could not be reached."""

    def __init__(self, message, status_code=None, code=None, data=None):
        super().__init__(message)
        # The web client picks the dialog by exception class name; an unknown
        # name (this subclass) falls back to the traceback dialog. Point it at
        # the plain UserError warning dialog instead.
        self.context = {'exception_class': 'odoo.exceptions.UserError'}
        self.status_code = status_code
        self.code = code
        self.data = data


class AbdmGateway(models.AbstractModel):
    """Client for the ABDM V3 gateway and ABHA services.

    Vertical modules call ``self.env['abdm.gateway']`` and never build HTTP
    requests themselves, so headers, tokens, retries and logging live here.
    """
    _name = 'abdm.gateway'
    _description = 'ABDM Gateway Client'

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    @api.model
    def _get_config(self):
        ICP = self.env['ir.config_parameter'].sudo()
        environment = ICP.get_str('abdm_base.environment') or 'sandbox'
        defaults = const.ENVIRONMENTS.get(environment, const.ENVIRONMENTS['sandbox'])
        return {
            'environment': environment,
            'client_id': (ICP.get_str('abdm_base.client_id') or '').strip(),
            'client_secret': (ICP.get_str('abdm_base.client_secret') or '').strip(),
            'gateway_url': (ICP.get_str('abdm_base.gateway_url') or defaults['gateway_url']).rstrip('/'),
            'abha_url': (ICP.get_str('abdm_base.abha_url') or defaults['abha_url']).rstrip('/'),
            'cm_id': (ICP.get_str('abdm_base.cm_id') or defaults['cm_id']).strip(),
            'callback_url': (ICP.get_str('abdm_base.callback_url') or '').strip().rstrip('/'),
            'timeout': ICP.get_int('abdm_base.timeout', const.DEFAULT_TIMEOUT) or const.DEFAULT_TIMEOUT,
            'verify_callbacks': ICP.get_bool('abdm_base.verify_callbacks', True),
        }

    @api.model
    def _check_config(self, config=None):
        config = config or self._get_config()
        if not config['client_id'] or not config['client_secret']:
            raise UserError(self.env._(
                "ABDM is not configured. Enter the Client ID and Client Secret in "
                "Settings > ABDM."))
        return config

    @api.model
    def _cache_key(self, config):
        return (self.env.cr.dbname, config['environment'], config['client_id'], config['gateway_url'])

    @api.model
    def _new_request_id(self):
        return str(uuid.uuid4())

    @api.model
    def _timestamp(self):
        now = datetime.now(timezone.utc)
        return now.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (now.microsecond // 1000)

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------
    @api.model
    def _send(self, method, url, *, config, payload=None, headers=None, request_id=None,
              log_endpoint=None, raw=False, abdm_headers=True, log_body=None, data=None):
        """Perform one HTTP call and log it. Returns (status_code, parsed body).

        With ``raw=True`` a successful body is returned as bytes (files such as
        the ABHA card) and only its size is logged.

        Other ABDM services (e.g. NHCX) reuse this method for logging and error
        handling: ``abdm_headers=False`` leaves out the HIE-CM headers
        (REQUEST-ID, TIMESTAMP, X-CM-ID), ``log_body`` replaces what is logged
        (e.g. the readable payload instead of its encrypted form) and ``data``
        sends a pre-encoded body (form posts) instead of JSON.
        """
        request_id = request_id or self._new_request_id()
        all_headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        if abdm_headers:
            all_headers.update({
                'REQUEST-ID': request_id,
                'TIMESTAMP': self._timestamp(),
                'X-CM-ID': config['cm_id'],
            })
        all_headers.update(headers or {})
        log_vals = {
            'direction': 'outgoing',
            'environment': config['environment'],
            'method': method,
            'endpoint': log_endpoint or url,
            'request_id': request_id,
            'request_headers': {k: v for k, v in all_headers.items() if k.lower() != 'authorization'},
            'request_body': log_body if log_body is not None else payload,
        }
        if data is None and payload is not None:
            data = json.dumps(payload)
        started = time.monotonic()
        try:
            response = requests.request(
                method, url, headers=all_headers, data=data,
                timeout=config['timeout'],
            )
        except requests.RequestException as exc:
            log_vals.update(state='error', error_message=str(exc),
                            duration_ms=int((time.monotonic() - started) * 1000))
            self.env['abdm.api.log']._log(**log_vals)
            _logger.warning("ABDM call %s %s failed: %s", method, url, exc)
            raise AbdmError(self.env._(
                "Could not reach ABDM (%(url)s). Check the internet connection and "
                "try again.\n\nDetails: %(error)s", url=url, error=exc)) from exc

        ok = 200 <= response.status_code < 300
        if raw and ok:
            body = response.content
            logged_body = '<%s bytes, %s>' % (len(body), response.headers.get('Content-Type', '?'))
        else:
            try:
                body = response.json() if response.content else None
            except ValueError:
                body = response.text
            logged_body = body
        log_vals.update(
            status_code=response.status_code,
            response_body=logged_body,
            state='success' if ok else 'error',
            duration_ms=int((time.monotonic() - started) * 1000),
            error_message=False if ok else self._extract_error(body, response.status_code),
        )
        self.env['abdm.api.log']._log(**log_vals)
        return response.status_code, body

    @api.model
    def _extract_error(self, body, status_code):
        """Turn the various ABDM error shapes into one readable line."""
        if isinstance(body, dict):
            err = body.get('error') if isinstance(body.get('error'), dict) else body
            code = err.get('code') or ''
            message = err.get('message') or err.get('description') or ''
            if code or message:
                return ('%s %s' % (code, message)).strip()
            # Validation errors come as {"field": "reason", ...}
            details = ['%s: %s' % (k, v) for k, v in body.items()
                       if isinstance(v, (str, int)) and k not in ('timestamp', 'path', 'status')]
            if details:
                return '; '.join(details)[:500]
        if isinstance(body, list) and body and isinstance(body[0], dict):
            return self._extract_error(body[0], status_code)
        if isinstance(body, str) and body.strip():
            return body.strip()[:500]
        return self.env._("HTTP error %s", status_code)

    # ------------------------------------------------------------------
    # Session token
    # ------------------------------------------------------------------
    @api.model
    def _get_access_token(self, force_refresh=False):
        config = self._check_config()
        key = self._cache_key(config)
        if not force_refresh:
            with _CACHE_LOCK:
                cached = _TOKEN_CACHE.get(key)
            if cached and cached[1] > time.time():
                return cached[0]

        status, body = self._send(
            'POST', config['gateway_url'] + const.PATH_SESSIONS, config=config,
            payload={
                'clientId': config['client_id'],
                'clientSecret': config['client_secret'],
                'grantType': 'client_credentials',
            },
            log_endpoint=const.PATH_SESSIONS,
        )
        token = isinstance(body, dict) and body.get('accessToken')
        if not (200 <= status < 300) or not token:
            raise AbdmError(self.env._(
                "ABDM refused the login (HTTP %(status)s): %(error)s\n\n"
                "Check the Client ID, Client Secret and environment in Settings > ABDM.",
                status=status, error=self._extract_error(body, status)),
                status_code=status, data=body)
        expires_in = int(body.get('expiresIn') or 1200)
        expires_at = time.time() + max(expires_in - const.TOKEN_EXPIRY_MARGIN, 30)
        with _CACHE_LOCK:
            _TOKEN_CACHE[key] = (token, expires_at)
        return token

    @api.model
    def _clear_caches(self):
        config = self._get_config()
        key = self._cache_key(config)
        with _CACHE_LOCK:
            _TOKEN_CACHE.pop(key, None)
            _JWKS_CACHE.pop(key, None)
            _ABHA_KEY_CACHE.pop(key, None)

    # ------------------------------------------------------------------
    # Authenticated calls: the API vertical modules use
    # ------------------------------------------------------------------
    @api.model
    def _request(self, method, path, payload=None, *, service='gateway', headers=None,
                 request_id=None, raise_on_error=True, raw=False):
        """Call an ABDM API with a valid session token.

        :param service: 'gateway' (HIE-CM) or 'abha'
        :return: dict(status=..., data=..., request_id=...)
        """
        config = self._check_config()
        base_url = config['abha_url'] if service == 'abha' else config['gateway_url']
        request_id = request_id or self._new_request_id()
        result = None
        for attempt in range(2):
            token = self._get_access_token(force_refresh=attempt > 0)
            all_headers = {'Authorization': 'Bearer %s' % token}
            all_headers.update(headers or {})
            status, body = self._send(
                method, base_url + path, config=config, payload=payload,
                headers=all_headers, request_id=request_id,
                log_endpoint='%s:%s' % (service, path), raw=raw,
            )
            result = {'status': status, 'data': body, 'request_id': request_id}
            if status != 401:
                break
            # Token expired early or was revoked: refresh once and retry.
        if raise_on_error and not (200 <= result['status'] < 300):
            body = result['data']
            code = None
            if isinstance(body, dict):
                err = body.get('error') if isinstance(body.get('error'), dict) else body
                code = err.get('code')
            raise AbdmError(self.env._(
                "ABDM returned an error (HTTP %(status)s): %(error)s",
                status=result['status'], error=self._extract_error(body, result['status'])),
                status_code=result['status'], code=code, data=body)
        return result

    @api.model
    def _send_async(self, operation, path, payload, *, service='gateway', headers=None,
                    record=None, context_data=None):
        """Send a request whose real answer arrives later on the callback URL.

        Creates an ``abdm.transaction`` the callback controller matches through
        the REQUEST-ID. ``record`` (optional) is the Odoo record that asked.
        """
        request_id = self._new_request_id()
        tx = self.env['abdm.transaction'].sudo().create({
            'operation': operation,
            'request_id': request_id,
            'res_model': record._name if record else False,
            'res_id': record.id if record else False,
            'company_id': (record.company_id.id if record and 'company_id' in record._fields
                           and record.company_id else self.env.company.id),
            'context_data': context_data or False,
        })
        tx._set_request(payload)
        try:
            self._request('POST', path, payload, service=service, headers=headers,
                          request_id=request_id)
        except AbdmError as exc:
            tx._set_error(exc.args[0] if exc.args else exc)
            raise
        return tx

    # ------------------------------------------------------------------
    # Ready-made operations
    # ------------------------------------------------------------------
    @api.model
    def test_connection(self):
        """Log in with the configured credentials. Returns a short status dict."""
        self._clear_caches()
        config = self._check_config()
        self._get_access_token(force_refresh=True)
        return {
            'environment': config['environment'],
            'gateway_url': config['gateway_url'],
            'cm_id': config['cm_id'],
        }

    @api.model
    def register_bridge_url(self, url=None):
        """Tell ABDM where to send callbacks (our public HTTPS address)."""
        url = (url or self._get_config()['callback_url'] or '').rstrip('/')
        if not url:
            raise UserError(self.env._("Enter the public Callback URL first (e.g. https://yourdomain.com)."))
        if not url.startswith('https://'):
            raise UserError(self.env._("ABDM only calls HTTPS addresses. The Callback URL must start with https://"))
        return self._request('PATCH', const.PATH_BRIDGE_URL, {'url': url})

    @api.model
    def get_bridge_services(self):
        """Return the facilities / services ABDM has linked to our client ID."""
        return self._request('GET', const.PATH_BRIDGE_SERVICES)['data']

    # ------------------------------------------------------------------
    # ABHA encryption (Aadhaar, OTP and mobile are sent RSA-encrypted)
    # ------------------------------------------------------------------
    @api.model
    def _get_abha_public_key(self):
        config = self._check_config()
        key = self._cache_key(config)
        with _CACHE_LOCK:
            cached = _ABHA_KEY_CACHE.get(key)
        if cached and time.time() - cached[1] < ABHA_KEY_TTL:
            return cached[0]
        data = self._request('GET', const.PATH_ABHA_PUBLIC_CERT, service='abha')['data']
        pem = data.get('publicKey') if isinstance(data, dict) else data
        if not pem:
            raise AbdmError(self.env._("ABDM did not return the ABHA public key."), data=data)
        pem = pem.strip()
        if 'BEGIN' not in pem:
            pem = '-----BEGIN PUBLIC KEY-----\n%s\n-----END PUBLIC KEY-----' % pem
        public_key = serialization.load_pem_public_key(pem.encode())
        with _CACHE_LOCK:
            _ABHA_KEY_CACHE[key] = (public_key, time.time())
        return public_key

    @api.model
    def abha_encrypt(self, text):
        """Encrypt a value (Aadhaar, OTP, mobile...) for the ABHA V3 APIs.

        Algorithm required by ABHA: RSA/ECB/OAEPWithSHA-1AndMGF1Padding.
        """
        public_key = self._get_abha_public_key()
        cipher = public_key.encrypt(
            str(text).encode(),
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA1()), algorithm=hashes.SHA1(), label=None),
        )
        return base64.b64encode(cipher).decode()

    # ------------------------------------------------------------------
    # Verification of incoming callbacks
    # ------------------------------------------------------------------
    @api.model
    def _get_gateway_jwks(self, force_refresh=False):
        config = self._check_config()
        key = self._cache_key(config)
        with _CACHE_LOCK:
            cached = _JWKS_CACHE.get(key)
        if cached and not force_refresh and time.time() - cached[1] < JWKS_TTL:
            return cached[0]
        jwks = self._request('GET', const.PATH_CERTS)['data'] or {}
        with _CACHE_LOCK:
            _JWKS_CACHE[key] = (jwks, time.time())
        return jwks

    @api.model
    def _verify_callback_token(self, authorization):
        """Check the gateway-signed JWT ABDM sends with every callback.

        Returns the token claims, or raises ValueError when it is invalid.
        """
        if not authorization:
            raise ValueError('missing Authorization header')
        token = authorization.split(' ', 1)[1] if ' ' in authorization else authorization
        try:
            header_b64, claims_b64, signature_b64 = token.split('.')
            header = json.loads(_b64url_decode(header_b64))
            claims = json.loads(_b64url_decode(claims_b64))
            signature = _b64url_decode(signature_b64)
        except (ValueError, TypeError) as exc:
            raise ValueError('malformed token') from exc
        if header.get('alg') != 'RS256':
            raise ValueError('unsupported algorithm %s' % header.get('alg'))

        def find_key(jwks):
            for jwk in (jwks or {}).get('keys', []):
                if not header.get('kid') or jwk.get('kid') == header.get('kid'):
                    return jwk
            return None

        jwk = find_key(self._get_gateway_jwks())
        if not jwk:  # keys rotated: refresh once
            jwk = find_key(self._get_gateway_jwks(force_refresh=True))
        if not jwk:
            raise ValueError('unknown signing key')
        public_key = rsa.RSAPublicNumbers(
            int.from_bytes(_b64url_decode(jwk['e']), 'big'),
            int.from_bytes(_b64url_decode(jwk['n']), 'big'),
        ).public_key()
        try:
            public_key.verify(signature, ('%s.%s' % (header_b64, claims_b64)).encode(),
                              padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature as exc:
            raise ValueError('invalid signature') from exc
        if claims.get('exp') and float(claims['exp']) < time.time() - 60:
            raise ValueError('token expired')
        return claims

    # ------------------------------------------------------------------
    # Callback dispatch: vertical modules extend this
    # ------------------------------------------------------------------
    @api.model
    def _handle_callback(self, path, payload, headers):
        """Process a callback ABDM sent to /api/v3/<path>.

        Base behaviour: when the body carries ``response.requestId``, store the
        answer on the matching transaction. Vertical modules override this
        method, call super() and react to the paths they own (e.g. care-context
        discovery or consent notifications). Return a transaction or None.
        """
        response = payload.get('response') if isinstance(payload, dict) else None
        request_id = isinstance(response, dict) and response.get('requestId')
        tx = self.env['abdm.transaction']._find_by_request_id(request_id)
        if tx:
            tx._set_response(payload, callback_path=path)
            return tx
        return None
