# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
from odoo.exceptions import UserError

DEFAULT_REMOTE_URL = 'https://hudson-social.odoo.com'
DEFAULT_REMOTE_DB = 'hudson-social'
DEFAULT_REMOTE_EMAIL = 'nandusaji20012001@gmail.com'
DEFAULT_API_KEY = '04faf49029b6972ebea6c145572b4060bf372e05'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ------------------------------------------------------------------
    # Social Marketing connector settings
    # ------------------------------------------------------------------
    social_remote_url = fields.Char(
        string='Remote Odoo URL',
        config_parameter='hudson_social.remote_url',
        default=DEFAULT_REMOTE_URL,
        help='Base URL of the remote Odoo instance (e.g. https://hudson-social.odoo.com)',
    )
    social_remote_db = fields.Char(
        string='Remote Database',
        config_parameter='hudson_social.remote_db',
        default=DEFAULT_REMOTE_DB,
        help='Database name on the remote Odoo instance.',
    )
    social_remote_email = fields.Char(
        string='Remote User Email',
        config_parameter='hudson_social.remote_email',
        default=DEFAULT_REMOTE_EMAIL,
        help='Email address of the user on the remote Odoo instance.',
    )
    social_api_key = fields.Char(
        string='API Key',
        config_parameter='hudson_social.api_key',
        default=DEFAULT_API_KEY,
        help='API Key generated in the remote Odoo instance (Settings > API Keys).',
    )
    social_sync_interval = fields.Integer(
        string='Sync Interval (minutes)',
        config_parameter='hudson_social.sync_interval',
        default=5,
        help='How often the scheduled action will sync data from the remote instance.',
    )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_social_test_connection(self):
        """Test the API connection and show a notification."""
        self.env['ir.config_parameter'].sudo().set_param(
            'hudson_social.remote_url', self.social_remote_url or DEFAULT_REMOTE_URL
        )
        self.env['ir.config_parameter'].sudo().set_param(
            'hudson_social.remote_db', self.social_remote_db or DEFAULT_REMOTE_DB
        )
        self.env['ir.config_parameter'].sudo().set_param(
            'hudson_social.remote_email', self.social_remote_email or DEFAULT_REMOTE_EMAIL
        )
        self.env['ir.config_parameter'].sudo().set_param(
            'hudson_social.api_key', self.social_api_key or DEFAULT_API_KEY
        )

        SocialAccount = self.env['hudson.social.account']
        ok, message = SocialAccount._social_check_connection()
        notification_type = 'success' if ok else 'danger'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Connection Test'),
                'message': message,
                'type': notification_type,
                'sticky': not ok,
            },
        }

    def action_social_sync_now(self):
        """Trigger a full sync immediately."""
        self.env['hudson.social.post'].sudo().action_sync_all()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Complete'),
                'message': _('All social media data has been synced from the remote instance.'),
                'type': 'success',
                'sticky': False,
            },
        }
