# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

import base64
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MEDIA_TYPE_SELECTION = [
    ('facebook', 'Facebook'),
    ('twitter', 'Twitter / X'),
    ('instagram', 'Instagram'),
    ('linkedin', 'LinkedIn'),
    ('youtube', 'YouTube'),
    ('pinterest', 'Pinterest'),
    ('push_notifications', 'Push Notifications'),
    ('other', 'Other'),
]

# Map remote media field values → local selection key
MEDIA_TYPE_MAP = {
    'facebook': 'facebook',
    'twitter': 'twitter',
    'instagram': 'instagram',
    'linkedin': 'linkedin',
    'youtube': 'youtube',
    'pinterest': 'pinterest',
    'push_notifications': 'push_notifications',
}


class HudsonSocialAccount(models.Model):
    _name = 'hudson.social.account'
    _description = 'Social Media Account'
    _inherit = ['hudson.social.connector']
    _rec_name = 'name'
    _order = 'media_type, name'

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    name = fields.Char(string='Account Name', required=True, index=True)
    media_type = fields.Selection(
        selection=MEDIA_TYPE_SELECTION,
        string='Platform',
        default='other',
        required=True,
    )
    social_account_handle = fields.Char(string='Handle / Username')
    is_media_disconnected = fields.Boolean(
        string='Disconnected',
        default=False,
        help='True if the remote account token has expired or been revoked.',
    )
    audience = fields.Integer(string='Audience', default=0)
    followers = fields.Integer(string='Followers', default=0)
    image = fields.Image(string='Profile Image', max_width=256, max_height=256)
    image_url = fields.Char(string='Profile Image URL')

    # Remote reference
    remote_id = fields.Integer(
        string='Remote ID',
        index=True,
        help='ID of this record on the remote Odoo instance.',
    )
    last_sync = fields.Datetime(string='Last Synced', readonly=True)

    # Computed
    media_type_icon = fields.Char(
        string='Platform Icon',
        compute='_compute_media_type_icon',
        store=False,
    )
    post_count = fields.Integer(
        string='Posts',
        compute='_compute_post_count',
    )

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    _sql_constraints = [
        ('remote_id_unique', 'UNIQUE(remote_id)', 'Each remote social account must be unique.'),
    ]

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends('media_type')
    def _compute_media_type_icon(self):
        icon_map = {
            'facebook': 'fa-facebook',
            'twitter': 'fa-twitter',
            'instagram': 'fa-instagram',
            'linkedin': 'fa-linkedin',
            'youtube': 'fa-youtube',
            'pinterest': 'fa-pinterest',
            'push_notifications': 'fa-bell',
            'other': 'fa-globe',
        }
        for rec in self:
            rec.media_type_icon = icon_map.get(rec.media_type, 'fa-globe')

    def _compute_post_count(self):
        for rec in self:
            rec.post_count = self.env['hudson.social.post'].search_count(
                [('account_ids', 'in', [rec.id])]
            )

    # ------------------------------------------------------------------
    # CRUD hooks
    # ------------------------------------------------------------------

    def name_get(self):
        result = []
        platform_labels = dict(MEDIA_TYPE_SELECTION)
        for rec in self:
            platform = platform_labels.get(rec.media_type, '')
            display = f"[{platform}] {rec.name}" if platform else rec.name
            result.append((rec.id, display))
        return result

    # ------------------------------------------------------------------
    # Sync from remote
    # ------------------------------------------------------------------

    @api.model
    def sync_from_remote(self):
        """Fetch all social.account records from the remote Odoo instance."""
        _logger.info("Syncing social accounts from remote...")
        try:
            remote_accounts = self._social_search_read(
                'social.account',
                domain=[],
                fields=['id', 'name', 'media_type', 'social_account_handle',
                        'is_media_disconnected', 'audience'],
                limit=500,
            )
        except UserError as e:
            _logger.error("Failed to sync social accounts: %s", e)
            return False

        for remote in remote_accounts:
            rid = remote.get('id')
            existing = self.search([('remote_id', '=', rid)], limit=1)
            media_type = MEDIA_TYPE_MAP.get(
                (remote.get('media_type') or '').lower(), 'other'
            )
            vals = {
                'name': remote.get('name') or _('Unknown Account'),
                'media_type': media_type,
                'social_account_handle': remote.get('social_account_handle') or '',
                'is_media_disconnected': remote.get('is_media_disconnected') or False,
                'audience': remote.get('audience') or 0,
                'followers': remote.get('followers') or 0,
                'remote_id': rid,
                'last_sync': fields.Datetime.now(),
            }
            if existing:
                existing.write(vals)
            else:
                self.create(vals)

        _logger.info("Social accounts sync complete — %d records processed.", len(remote_accounts))
        return True

    def action_view_posts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Posts — %s') % self.name,
            'res_model': 'hudson.social.post',
            'view_mode': 'list,form',
            'domain': [('account_ids', 'in', [self.id])],
            'context': {'default_account_ids': [self.id]},
        }
