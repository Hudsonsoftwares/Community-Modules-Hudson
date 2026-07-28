# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HudsonSocialComment(models.Model):
    """Stores comments fetched from social media platforms via the remote
    Odoo Enterprise instance.

    Comments are NOT stored as records on the remote — they are fetched live
    from each platform (Twitter, LinkedIn, etc.) via the social.stream.post
    model's `get_comments` method.

    To sync, click "Sync Comments" on a published post.
    """
    _name = 'hudson.social.comment'
    _description = 'Social Media Comment'
    _order = 'published_date desc, id desc'
    _rec_name = 'author_name'

    post_id = fields.Many2one(
        'hudson.social.post',
        string='Post',
        required=True,
        ondelete='cascade',
        index=True,
    )
    author_name = fields.Char(string='Author', readonly=True)
    author_avatar_url = fields.Char(string='Author Avatar URL', readonly=True)
    message = fields.Text(string='Comment', readonly=True)
    published_date = fields.Datetime(string='Date', readonly=True)
    platform = fields.Selection(
        selection=[
            ('twitter', 'Twitter / X'),
            ('linkedin', 'LinkedIn'),
            ('facebook', 'Facebook'),
            ('instagram', 'Instagram'),
            ('youtube', 'YouTube'),
            ('other', 'Other'),
        ],
        string='Platform',
        readonly=True,
    )
    likes_count = fields.Integer(string='Likes', default=0, readonly=True)
    comment_link = fields.Char(string='Link', readonly=True)
    # Unique key from the remote so we don't duplicate
    remote_key = fields.Char(
        string='Remote Key',
        readonly=True,
        index=True,
        help='Unique key combining platform + remote comment ID to prevent duplicates.',
    )

    # Stream stats stored on the post's stream post (aggregated from remote)
    twitter_screen_name = fields.Char(string='Screen Name', readonly=True)

    _sql_constraints = [
        ('unique_remote_key_post',
         'UNIQUE(post_id, remote_key)',
         'A comment with this remote key already exists for this post.'),
    ]
