import json
import logging
import time

from odoo import http
from odoo.http import request

from .. import const

_logger = logging.getLogger(__name__)

LOGGED_HEADERS = ('Content-Type', 'User-Agent', 'X-Forwarded-For')


class NhcxCallbackController(http.Controller):
    """Endpoint the exchange calls with payers' answers.

    Register ``<public URL>/nhcx`` as the endpoint URL during NHCX onboarding;
    the exchange then posts to ``/nhcx/coverageeligibility/on_check`` etc.
    Like the ABDM callbacks, the request carries no database name: the server
    needs a ``dbfilter`` selecting one database for this domain.

    Authenticity: the payload must decrypt with this facility's private key,
    its correlation ID must match a request we sent, and its sender must be
    the payer that request went to.
    """

    @http.route('/nhcx/<path:action>', type='http', auth='public', methods=['POST'],
                csrf=False, save_session=False)
    def nhcx_callback(self, action, **kwargs):
        started = time.monotonic()
        env = request.env(su=True)
        config = env['abdm.gateway']._get_config()
        httprequest = request.httprequest
        raw = httprequest.get_data()
        log_vals = {
            'direction': 'incoming',
            'environment': config['environment'],
            'method': 'POST',
            'endpoint': '/nhcx/' + action,
            'request_headers': {k: v for k, v in httprequest.headers.items() if k in LOGGED_HEADERS},
            # the body is encrypted: log only its size, the transaction keeps the answer
            'request_body': '<%s bytes>' % len(raw or b''),
        }

        def reply(status, body, error=None):
            log_vals.update(status_code=status, state='error' if error else 'success',
                            error_message=error or False, response_body=body,
                            duration_ms=int((time.monotonic() - started) * 1000))
            env['abdm.api.log']._log(**log_vals)
            return request.make_response(json.dumps(body), status=status,
                                         headers=[('Content-Type', 'application/json')])

        action = action.strip('/')
        if action not in const.CALLBACK_ACTIONS:
            _logger.info("NHCX callback on unknown action %s", action)
        try:
            body = json.loads(raw or b'{}')
        except ValueError:
            return reply(400, {'error': 'invalid JSON'}, 'Body is not valid JSON')
        try:
            with env.cr.savepoint():
                status, ack, error = env['nhcx.client'].handle_callback(action, body)
        except Exception as exc:  # noqa: BLE001 - never return a stack trace to the exchange
            _logger.exception("Error while processing NHCX callback %s", action)
            return reply(500, {'error': 'processing error'}, 'Processing error: %s' % exc)
        if ack.get('correlation_id'):
            log_vals['request_id'] = ack['correlation_id']
            log_vals['correlation_id'] = ack['correlation_id']
        return reply(status, ack, error)
