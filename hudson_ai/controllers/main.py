# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

import logging

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from ..models.ai_provider import AIProviderError

_logger = logging.getLogger(__name__)


def _safe(func):
    """Return {'error': message} instead of a traceback dialog for expected errors."""
    try:
        return func()
    except (AIProviderError, UserError, AccessError) as e:
        return {'error': str(e.args[0] if e.args else e)}
    except Exception:
        _logger.exception('Hudson AI request failed')
        return {'error': 'Unexpected error, see the server log.'}


class HudsonAIController(http.Controller):

    @http.route('/hudson_ai/chat', type='jsonrpc', auth='user')
    def chat(self, message, history=None, record=None):
        message = (message or '').strip()
        if not message:
            return {'error': 'Empty message.'}
        return _safe(lambda: request.env['hudson.ai.agent'].chat(message, history, record))

    @http.route('/hudson_ai/summarize', type='jsonrpc', auth='user')
    def summarize(self, model, res_id):
        return _safe(lambda: {
            'reply': request.env['hudson.ai.agent'].summarize_record(model, int(res_id))})

    @http.route('/hudson_ai/write', type='jsonrpc', auth='user')
    def write(self, instruction):
        return _safe(lambda: request.env['hudson.ai.agent'].write_article(instruction))

    @http.route('/hudson_ai/draft', type='jsonrpc', auth='user')
    def draft(self, model, res_id, instruction):
        return _safe(lambda: {
            'reply': request.env['hudson.ai.agent'].draft_message(model, int(res_id), instruction)})
