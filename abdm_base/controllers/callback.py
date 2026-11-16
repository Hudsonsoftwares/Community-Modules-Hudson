import json
import logging
import time

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

LOGGED_HEADERS = ('REQUEST-ID', 'TIMESTAMP', 'X-CM-ID', 'X-HIP-ID', 'X-HIU-ID', 'Content-Type')


class AbdmCallbackController(http.Controller):
    """Receives the asynchronous answers ABDM sends to our bridge URL.

    ABDM calls <bridge URL>/api/v3/<path>, so the bridge URL registered with
    ABDM must be the bare public address of this Odoo (https://yourdomain.com).
    The request carries no database name: the server must run with a
    ``dbfilter`` that selects exactly one database for this domain.
    """

    @http.route('/api/v3/<path:subpath>', type='http', auth='public', methods=['POST'],
                csrf=False, save_session=False)
    def abdm_callback(self, subpath, **kwargs):
        started = time.monotonic()
        httprequest = request.httprequest
        path = '/api/v3/' + subpath
        env = request.env(su=True)
        gateway = env['abdm.gateway']
        Log = env['abdm.api.log']
        config = gateway._get_config()

        raw = httprequest.get_data()
        headers = {key: value for key, value in httprequest.headers.items()}
        log_vals = {
            'direction': 'incoming',
            'environment': config['environment'],
            'method': 'POST',
            'endpoint': path,
            'request_id': headers.get('Request-Id') or headers.get('REQUEST-ID'),
            'request_headers': {k: v for k, v in headers.items()
                                if k.upper() in LOGGED_HEADERS},
            'request_body': raw,
        }

        def reply(status, error=None):
            log_vals.update(
                status_code=status,
                state='error' if error else 'success',
                error_message=error or False,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            Log._log(**log_vals)
            return request.make_response('', status=status)

        try:
            payload = json.loads(raw or b'{}')
        except ValueError:
            return reply(400, 'Body is not valid JSON')
        response = payload.get('response') if isinstance(payload, dict) else None
        if isinstance(response, dict):
            log_vals['correlation_id'] = response.get('requestId')

        if config['verify_callbacks']:
            try:
                gateway._verify_callback_token(headers.get('Authorization'))
            except (ValueError, UserError) as exc:
                _logger.warning("Rejected ABDM callback %s: %s", path, exc)
                return reply(401, 'Signature check failed: %s' % exc)

        try:
            with env.cr.savepoint():
                gateway._handle_callback(path, payload, headers)
        except Exception as exc:  # noqa: BLE001 - never let ABDM see a stack trace
            _logger.exception("Error while processing ABDM callback %s", path)
            # Acknowledge anyway: ABDM does not retry, the log keeps the details.
            return reply(202, 'Processing error: %s' % exc)
        return reply(202)
