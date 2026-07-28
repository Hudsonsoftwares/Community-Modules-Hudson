# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class HudsonAIController(http.Controller):
    """HTTP endpoints consumed by the OWL frontend components."""

    # ── /hudson_ai/config ────────────────────────────────────────────────────
    @http.route('/hudson_ai/config', type='http', auth='user', methods=['GET'], csrf=False)
    def get_config(self, **kwargs):
        """Return current AI config as JSON (safe subset — no API key)."""
        try:
            cfg = request.env['hudson.ai.config'].sudo().get_config_dict()
            return request.make_response(
                json.dumps({
                    'enabled': cfg.get('enabled', True),
                    'model_name': cfg.get('model_name', ''),
                    'base_url': cfg.get('base_url', ''),
                }),
                headers=[('Content-Type', 'application/json')],
            )
        except Exception as e:
            _logger.error('Hudson AI /config error: %s', e)
            return request.make_response(
                json.dumps({'error': str(e)}),
                headers=[('Content-Type', 'application/json')],
                status=500,
            )

    # ── /hudson_ai/test_connection ────────────────────────────────────────────
    @http.route('/hudson_ai/test_connection', type='http', auth='user', methods=['GET'], csrf=False)
    def test_connection(self, **kwargs):
        """Ping the LM Studio server and return status."""
        try:
            cfg_record = request.env['hudson.ai.config'].sudo().get_config()
            cfg_record.action_test_connection()
            return request.make_response(
                json.dumps({'success': True, 'status': cfg_record.connection_status}),
                headers=[('Content-Type', 'application/json')],
            )
        except Exception as e:
            return request.make_response(
                json.dumps({'success': False, 'error': str(e)}),
                headers=[('Content-Type', 'application/json')],
                status=200,
            )

    # ── /hudson_ai/chat ───────────────────────────────────────────────────────
    @http.route('/hudson_ai/chat', type='json', auth='user', methods=['POST'], csrf=False)
    def chat(self, user_message='', conversation_history=None, **kwargs):
        """
        Process a chat message through the AI agent loop.

        Request JSON body:
          {
            "user_message": "Create a quotation for Azure Interior",
            "conversation_history": [
              {"role": "user", "content": "..."},
              {"role": "assistant", "content": "..."},
              ...
            ]
          }

        Response JSON:
          { "reply": "Done! I created quotation SO-0042 for Azure Interior." }
        """
        if not user_message:
            return {'error': 'user_message is required'}

        history = conversation_history or []
        try:
            reply = request.env['hudson.ai.agent'].process_message(history, user_message)
            return {'reply': reply}
        except Exception as e:
            _logger.exception('Hudson AI /chat error')
            return {'error': str(e)}

    # ── /hudson_ai/summarize_chatter ─────────────────────────────────────────
    @http.route('/hudson_ai/summarize_chatter', type='json', auth='user', methods=['POST'], csrf=False)
    def summarize_chatter(self, model_name='', record_id=None, **kwargs):
        """Summarize the chatter of a given record."""
        if not model_name or not record_id:
            return {'error': 'model_name and record_id are required'}
        try:
            summary = request.env['hudson.ai.agent'].summarize_chatter(model_name, int(record_id))
            return {'summary': summary}
        except Exception as e:
            _logger.exception('Hudson AI /summarize_chatter error')
            return {'error': str(e)}

    # ── /hudson_ai/draft_email ────────────────────────────────────────────────
    @http.route('/hudson_ai/draft_email', type='json', auth='user', methods=['POST'], csrf=False)
    def draft_email(self, model_name='', record_id=None, instruction='', **kwargs):
        """Draft an email or note for a given record."""
        if not model_name or not record_id or not instruction:
            return {'error': 'model_name, record_id, and instruction are required'}
        try:
            draft = request.env['hudson.ai.agent'].draft_email(
                model_name, int(record_id), instruction
            )
            return {'draft': draft}
        except Exception as e:
            _logger.exception('Hudson AI /draft_email error')
            return {'error': str(e)}
