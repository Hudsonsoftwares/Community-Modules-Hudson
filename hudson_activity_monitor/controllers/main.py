"""JSON endpoints used by the Hudson Activity desktop agent.

The agent selects the database with the ``X-Odoo-Database`` header and
authenticates with ``Authorization: Bearer <device token>``. No session is created.
"""
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

MAX_BODY = 5 * 1024 * 1024


class ActivityAgentController(http.Controller):

    def _json_body(self):
        raw = request.httprequest.get_data(cache=False, as_text=False)
        if len(raw) > MAX_BODY:
            return None
        try:
            body = json.loads(raw or b'{}')
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def _error(self, message, status):
        return request.make_json_response({'error': message}, status=status)

    @http.route('/api/activity/pair', type='http', auth='public', methods=['POST'],
                csrf=False, save_session=False)
    def pair(self):
        body = self._json_body()
        if body is None:
            return self._error('Invalid request body', 400)
        device, token = request.env['hr.activity.device'].sudo()._pair(body.get('code'), body)
        if not device:
            _logger.info("Activity agent pairing refused (host %s)", body.get('hostname'))
            return self._error('Invalid or expired pairing code', 400)
        _logger.info("Activity agent paired: %s for %s", device.name, device.employee_id.name)
        return request.make_json_response({
            'token': token,
            'employee': device.employee_id.name,
            'database': request.db,
            'config': device._agent_config(),
        })

    @http.route('/api/activity/ingest', type='http', auth='public', methods=['POST'],
                csrf=False, save_session=False)
    def ingest(self):
        auth = request.httprequest.headers.get('Authorization', '')
        token = auth[7:].strip() if auth.lower().startswith('bearer ') else ''
        device = request.env['hr.activity.device'].sudo()._authenticate(token)
        if not device:
            return self._error('Unknown or revoked device token', 401)
        body = self._json_body()
        if body is None:
            return self._error('Invalid request body', 400)
        accepted, rejected = device._ingest(body.get('spans') or [], body.get('agent_version'))
        if rejected:
            _logger.warning("Activity device %s: %s invalid spans rejected", device.id, rejected)
        return request.make_json_response({
            'accepted': accepted,
            'rejected': rejected,
            'config': device._agent_config(),
        })
