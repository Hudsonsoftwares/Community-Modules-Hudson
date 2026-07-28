# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class HudsonSocialController(http.Controller):
    """
    Optional HTTP controller for the Social Marketing module.
    Provides a manual sync trigger endpoint for testing/debugging.
    """

    @http.route(
        '/hudson_social/sync',
        type='json',
        auth='user',
        methods=['POST'],
        csrf=True,
    )
    def trigger_sync(self, **kwargs):
        """
        Manually trigger a full sync from the remote Odoo instance.
        Accessible to authenticated users only.

        Usage (dev mode):
            POST /hudson_social/sync
            Content-Type: application/json
            {"jsonrpc": "2.0", "method": "call", "params": {}}
        """
        try:
            request.env['hudson.social.post'].action_sync_all()
            return {'success': True, 'message': 'Sync completed successfully.'}
        except Exception as e:
            _logger.error("Manual sync failed: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route(
        '/hudson_social/status',
        type='json',
        auth='user',
        methods=['POST'],
        csrf=True,
    )
    def connection_status(self, **kwargs):
        """
        Check the API connection status.

        Usage:
            POST /hudson_social/status
        """
        SocialAccount = request.env['hudson.social.account']
        ok, message = SocialAccount._social_check_connection()
        return {
            'connected': ok,
            'message': message,
        }
