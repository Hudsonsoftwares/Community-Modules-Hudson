# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HudsonSocialStreamPost(models.Model):
    _name = 'hudson.social.stream.post'
    _description = 'Social Media Feed Post'
    _inherit = ['hudson.social.connector']
    _rec_name = 'author_name'
    _order = 'published_date desc'

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    account_id = fields.Many2one(
        comodel_name='hudson.social.account',
        string='Account',
        ondelete='cascade',
        index=True,
    )
    message = fields.Text(string='Message')
    author_name = fields.Char(string='Author')
    author_image_url = fields.Char(string='Author Image URL')
    published_date = fields.Datetime(string='Published')
    likes = fields.Integer(string='Likes', default=0)
    comments = fields.Integer(string='Comments', default=0)
    shares = fields.Integer(string='Shares', default=0)
    post_link = fields.Char(string='Original Post URL')

    # Remote reference
    remote_id = fields.Integer(string='Remote ID', index=True)
    last_sync = fields.Datetime(string='Last Synced', readonly=True)

    # Computed
    media_type = fields.Selection(
        related='account_id.media_type',
        string='Platform',
        store=True,
        readonly=True,
    )
    media_type_icon = fields.Char(
        related='account_id.media_type_icon',
        string='Platform Icon',
        store=False,
    )
    engagement_total = fields.Integer(
        string='Total Engagement',
        compute='_compute_engagement_total',
        store=True,
    )

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends('likes', 'comments', 'shares')
    def _compute_engagement_total(self):
        for rec in self:
            rec.engagement_total = (rec.likes or 0) + (rec.comments or 0) + (rec.shares or 0)

    # ------------------------------------------------------------------
    # Sync from remote
    # ------------------------------------------------------------------

    @api.model
    def sync_from_remote(self):
        """Pull stream posts from remote social.stream.post model."""
        _logger.info("Syncing social stream posts from remote...")
        SocialAccount = self.env['hudson.social.account']

        try:
            remote_posts = self._social_search_read(
                'social.stream.post',
                domain=[],
                fields=['id', 'account_id', 'message', 'author_name',
                        'published_date', 'likes_count', 'comments_count',
                        'shares_count', 'post_link'],
                limit=500,
                order='id desc',
            )
        except UserError as e:
            _logger.warning("social.stream.post not available on remote: %s", e)
            # Try alternative field names (older Odoo versions)
            try:
                remote_posts = self._social_search_read(
                    'social.stream.post',
                    domain=[],
                    fields=['id', 'account_id', 'message', 'author_name', 'published_date'],
                    limit=500,
                    order='id desc',
                )
            except UserError as e2:
                _logger.error("Cannot sync stream posts: %s", e2)
                return False

        for remote in remote_posts:
            rid = remote.get('id')
            existing = self.search([('remote_id', '=', rid)], limit=1)

            # Resolve account
            remote_acc = remote.get('account_id')
            local_account = False
            if remote_acc:
                remote_acc_id = remote_acc[0] if isinstance(remote_acc, (list, tuple)) else remote_acc
                local_account = SocialAccount.search([('remote_id', '=', remote_acc_id)], limit=1)

            vals = {
                'account_id': local_account.id if local_account else False,
                'message': remote.get('message') or '',
                'author_name': remote.get('author_name') or '',
                'published_date': remote.get('published_date') or False,
                'likes': remote.get('likes_count') or remote.get('likes') or 0,
                'comments': remote.get('comments_count') or remote.get('comments') or 0,
                'shares': remote.get('shares_count') or remote.get('shares') or 0,
                'post_link': remote.get('post_link') or '',
                'remote_id': rid,
                'last_sync': fields.Datetime.now(),
            }

            if existing:
                existing.write(vals)
            else:
                self.create(vals)

        _logger.info("Stream posts sync complete — %d records processed.", len(remote_posts))
        return True
