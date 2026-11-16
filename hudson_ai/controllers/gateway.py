# Part of Hudson Community. See LICENSE file for full copyright and licensing details.
"""OpenAI-compatible gateway: lets other Odoo databases use this database's AI key,
each with its own key and limits (Settings > Hudson AI > Gateway).

Client databases select the provider "Hudson AI Gateway" with
URL https://<this server>/hudson_ai/v1 and the key generated for them.
"""

import json
import logging

from odoo import http
from odoo.http import request

from ..models.ai_provider import MAX_TOKENS, QUOTA_STATUS, build_payload, forward, get_ai_settings, is_configured

_logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 2 * 1024 * 1024


def _json(status, body, headers=None):
    return request.make_response(
        json.dumps(body) if not isinstance(body, bytes) else body,
        headers=list((headers or {'Content-Type': 'application/json'}).items()),
        status=status,
    )


def _error(status, message, code):
    return _json(status, {'error': {'message': message, 'type': code, 'code': code}})


class HudsonAIGateway(http.Controller):

    def _authenticate(self):
        """Return (client, error response)."""
        if not request.db:
            return None, _error(404, 'No database selected: send the X-Odoo-Database header.', 'no_database')
        icp = request.env['ir.config_parameter'].sudo()
        if not icp.get_bool('hudson_ai.gateway_enabled'):
            return None, _error(404, 'The Hudson AI gateway is not enabled on this server.', 'gateway_disabled')
        auth = request.httprequest.headers.get('Authorization', '')
        key = auth.removeprefix('Bearer ').strip()
        client = request.env['hudson.ai.client']._authenticate(key)
        if not client:
            return None, _error(401, 'Invalid Hudson AI key.', 'invalid_api_key')
        return client, None

    @http.route('/hudson_ai/v1/chat/completions', type='http', auth='none', methods=['POST'],
                csrf=False, save_session=False)
    def chat_completions(self, **kwargs):
        # Always read the body first: answering before it is consumed makes the
        # server reset the connection and the client never sees the error.
        if (request.httprequest.content_length or 0) > MAX_BODY_BYTES:
            return _error(413, 'Request too large.', 'request_too_large')
        raw = request.httprequest.get_data(cache=False)
        client, error = self._authenticate()
        if error:
            return error
        quota = client._quota_error()
        if quota:
            return _error(QUOTA_STATUS, quota, 'insufficient_quota')

        cfg = get_ai_settings(request.env)
        if cfg['provider'] == 'hudson' or not is_configured(cfg):
            return _error(503, 'The gateway has no AI provider configured.', 'gateway_not_configured')
        try:
            body = json.loads(raw)
            messages = body['messages']
        except (ValueError, KeyError, TypeError):
            return _error(400, 'Invalid request body.', 'invalid_request')

        # The gateway decides the model and caps the answer size.
        payload = build_payload(cfg, messages, body.get('tools'),
                                max_tokens=min(int(body.get('max_tokens') or MAX_TOKENS), MAX_TOKENS))
        status, content, headers = forward(cfg, payload)
        if status == 200:
            try:
                usage = json.loads(content).get('usage') or {}
            except ValueError:
                usage = {}
            request.env['hudson.ai.usage']._log(usage, 'gateway', model=cfg['model'], client=client)
        else:
            _logger.info('Hudson AI gateway: upstream HTTP %s for client %s', status, client.name)
        return _json(status, content, headers)

    @http.route('/hudson_ai/v1/models', type='http', auth='none', methods=['GET'],
                csrf=False, save_session=False)
    def models(self, **kwargs):
        client, error = self._authenticate()
        if error:
            return error
        return _json(200, {'object': 'list', 'data': [{'id': 'gateway', 'object': 'model'}]})

    @http.route('/hudson_ai/v1/usage', type='http', auth='none', methods=['GET'],
                csrf=False, save_session=False)
    def usage(self, **kwargs):
        client, error = self._authenticate()
        if error:
            return error
        return _json(200, client._usage_summary())
