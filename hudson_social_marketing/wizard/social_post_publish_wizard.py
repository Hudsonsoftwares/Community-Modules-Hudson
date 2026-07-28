# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

import base64
import io
import logging
import time

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Per-platform image limits (bytes) — keep images under these thresholds
# to avoid "image too large" errors from the social media APIs
PLATFORM_IMAGE_LIMITS = {
    'twitter':   4 * 1024 * 1024,   # Twitter: 5 MB hard limit, use 4 MB to be safe
    'linkedin':  4 * 1024 * 1024,   # LinkedIn: 5 MB hard limit, use 4 MB
    'facebook':  4 * 1024 * 1024,   # Facebook: 4 MB recommended
    'instagram': 8 * 1024 * 1024,   # Instagram: 8 MB
    'youtube':   None,               # Video — skip
    'pinterest': 4 * 1024 * 1024,   # Pinterest: 4 MB
}

# Max dimension (px) to resize images to before upload — prevents API rejections
MAX_IMAGE_DIMENSION = 1920  # 1920 px on the longer side


def _compress_image_b64(raw_b64, max_bytes=4 * 1024 * 1024, max_dim=MAX_IMAGE_DIMENSION):
    """Compress a base64-encoded image so it fits under *max_bytes*.

    Uses Pillow (PIL) which is always available in Odoo.
    Returns a base64 string of the compressed image (JPEG).
    Falls back to the original if PIL is unavailable or the image is already small enough.
    """
    try:
        from PIL import Image as PILImage
    except ImportError:
        _logger.warning("Pillow not available — cannot compress image. Sending original.")
        return raw_b64

    try:
        raw_bytes = base64.b64decode(raw_b64)
        if len(raw_bytes) <= max_bytes:
            # Already small enough
            return raw_b64

        img = PILImage.open(io.BytesIO(raw_bytes))

        # Convert to RGB if needed (RGBA/P modes can't be saved as JPEG)
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')

        # Resize if dimensions are very large
        w, h = img.size
        if max(w, h) > max_dim:
            ratio = max_dim / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), PILImage.LANCZOS)

        # Try progressively lower quality until we hit the size target
        for quality in (85, 75, 65, 50, 40):
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=quality, optimize=True)
            compressed = buf.getvalue()
            if len(compressed) <= max_bytes:
                _logger.info(
                    "Image compressed: %d bytes → %d bytes (quality=%d)",
                    len(raw_bytes), len(compressed), quality,
                )
                return base64.b64encode(compressed).decode('utf-8')

        # Last resort — aggressively resize
        small = img.resize((int(img.width * 0.5), int(img.height * 0.5)), PILImage.LANCZOS)
        buf = io.BytesIO()
        small.save(buf, format='JPEG', quality=40, optimize=True)
        result = buf.getvalue()
        _logger.info(
            "Image aggressively resized: %d bytes → %d bytes",
            len(raw_bytes), len(result),
        )
        return base64.b64encode(result).decode('utf-8')

    except Exception as e:
        _logger.warning("Image compression failed: %s — sending original.", e)
        return raw_b64


class SocialPostPublishWizard(models.TransientModel):
    _name = 'hudson.social.post.publish.wizard'
    _description = 'Publish / Schedule Social Post'
    _inherit = ['hudson.social.connector']

    post_id = fields.Many2one(
        comodel_name='hudson.social.post',
        string='Post',
        required=True,
        ondelete='cascade',
    )
    publish_type = fields.Selection(
        selection=[
            ('now', 'Publish Now'),
            ('schedule', 'Schedule'),
        ],
        string='When to Publish',
        required=True,
        default='now',
    )
    scheduled_date = fields.Datetime(
        string='Scheduled Date',
        help='Date and time when the post will be published on the remote instance.',
    )
    message_preview = fields.Text(
        related='post_id.message',
        string='Post Message',
        readonly=True,
    )
    account_names = fields.Char(
        string='Platforms',
        compute='_compute_account_names',
    )

    @api.depends('post_id.account_ids')
    def _compute_account_names(self):
        for rec in self:
            if rec.post_id:
                names = rec.post_id.account_ids.mapped('name')
                rec.account_names = ', '.join(names) if names else _('No accounts selected')
            else:
                rec.account_names = ''

    # ------------------------------------------------------------------
    # Main confirm action
    # ------------------------------------------------------------------

    def action_confirm(self):
        """Sync the post to remote then trigger publish / schedule."""
        self.ensure_one()
        post = self.post_id

        # ── Step 1: Sync post (message + accounts + images) to remote ──
        try:
            post.action_sync_to_remote()
        except UserError as e:
            raise UserError(_("Failed to sync post to remote:\n%s") % str(e))

        if not post.remote_id:
            raise UserError(_(
                "Post could not be synced to the remote Odoo instance. "
                "Please check your connection settings."
            ))

        # ── Step 2: Publish or schedule on the remote ──
        if self.publish_type == 'now':
            return self._publish_now(post)
        else:
            return self._schedule_post(post)

    # ------------------------------------------------------------------
    # Publish Now
    # ------------------------------------------------------------------

    def _publish_now(self, post):
        """Call action_post on the remote and report real per-platform status."""
        try:
            self._social_execute(
                'social.post', 'action_post', [[post.remote_id]]
            )
            _logger.info(
                "action_post called on remote post id=%s (local id=%s)",
                post.remote_id, post.id,
            )
        except UserError as e:
            # Propagate the real error — do NOT silently fall back
            raise UserError(_(
                "Remote Odoo rejected the publish request:\n\n%s\n\n"
                "Common causes:\n"
                "• Social account OAuth token expired on the Enterprise server\n"
                "• The post has no active/connected social accounts\n"
                "• Content policy violation on the platform"
            ) % str(e))

        # Wait briefly then read live_post results.
        # Most platforms (Facebook, Instagram, LinkedIn, Twitter/X) process
        # live_posts synchronously — state goes directly to 'posted' or 'failed'.
        time.sleep(3)
        live_summary, overall_state = self._read_live_post_status(post.remote_id)

        # Update local state to reflect reality
        post.write({
            'state': overall_state,
            'last_sync': fields.Datetime.now(),
            'sync_error': False,
        })

        # If ALL platforms failed → delete the remote post so it
        # doesn't pollute the Enterprise dashboard either
        if overall_state == 'failed':
            try:
                self._social_execute(
                    'social.post', 'action_set_cancel', [[post.remote_id]]
                )
            except Exception:
                pass  # best-effort cleanup

        _logger.info(
            "Post %s (remote_id=%s) overall state after publish: %s",
            post.id, post.remote_id, overall_state,
        )

        if overall_state == 'posted':
            notif_type = 'success'
            title = _('Post Published! 🎉')
        elif overall_state == 'failed':
            notif_type = 'danger'
            title = _('Publish Failed')
        else:
            notif_type = 'info'
            title = _('Publishing in Progress…')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': live_summary or _(
                    'Your post has been sent to the remote Odoo instance. '
                    'Use "Check Status" to see the result.'
                ),
                'type': notif_type,
                'sticky': overall_state in ('failed',),
            },
        }

    # ------------------------------------------------------------------
    # Schedule
    # ------------------------------------------------------------------

    def _schedule_post(self, post):
        """Write scheduled_date on the remote and call action_schedule."""
        if not self.scheduled_date:
            raise UserError(_("Please select a date/time for scheduled posting."))

        sched_str = fields.Datetime.to_string(self.scheduled_date)

        try:
            self._social_write(
                'social.post', [post.remote_id],
                {'scheduled_date': sched_str},
            )
        except UserError as e:
            raise UserError(_("Failed to set scheduled date on remote:\n%s") % str(e))

        try:
            self._social_execute(
                'social.post', 'action_schedule', [[post.remote_id]],
                scheduled_date=sched_str,
            )
            _logger.info(
                "Post %s (remote_id=%s) scheduled for %s on remote.",
                post.id, post.remote_id, sched_str,
            )
        except UserError as e:
            _logger.warning("action_schedule failed (%s), trying direct state write.", e)
            try:
                self._social_write(
                    'social.post', [post.remote_id], {'state': 'scheduled'}
                )
            except UserError as e2:
                raise UserError(_("Failed to schedule post on remote:\n%s") % str(e2))

        post.write({
            'state': 'scheduled',
            'scheduled_date': self.scheduled_date,
            'last_sync': fields.Datetime.now(),
            'sync_error': False,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Post Scheduled'),
                'message': _('Your post is scheduled for %s on the remote Odoo instance.') % sched_str,
                'type': 'success',
                'sticky': False,
            },
        }

    # ------------------------------------------------------------------
    # Live post status reader
    # ------------------------------------------------------------------

    def _read_live_post_status(self, remote_post_id):
        """Read social.live.post records for the remote post.

        Returns (summary_str, overall_local_state).
        Per the technical guide: social.live.post has state + failure_reason + live_post_link.
        """
        try:
            remote_data = self._social_execute(
                'social.post', 'read',
                [[remote_post_id]],
                fields=['live_post_ids', 'state'],
            )
        except UserError as e:
            _logger.warning("Could not read remote post state: %s", e)
            return None, 'posting'

        if not remote_data:
            return None, 'posting'

        remote_state = remote_data[0].get('state', 'posting')
        live_post_ids = remote_data[0].get('live_post_ids') or []

        if not live_post_ids:
            local_state = self._map_remote_state(remote_state)
            return (
                _('Remote post state: %s') % remote_state.upper(),
                local_state,
            )

        try:
            live_details = self._social_execute(
                'social.live.post', 'read',
                [live_post_ids],
                fields=['state', 'failure_reason', 'live_post_link', 'media_type'],
            )
        except UserError as e:
            _logger.warning("Could not read live post details: %s", e)
            return None, self._map_remote_state(remote_state)

        lines = []
        any_failed = False
        any_posting = False
        any_posted = False

        for lp in (live_details or []):
            lp_state = lp.get('state', 'posting')
            media = (lp.get('media_type') or 'unknown').capitalize()
            link = lp.get('live_post_link') or ''
            reason = lp.get('failure_reason') or ''

            if lp_state == 'posted':
                any_posted = True
                line = '✅ %s: Published' % media
                if link:
                    line += '\n   %s' % link
            elif lp_state == 'failed':
                any_failed = True
                line = '❌ %s: Failed' % media
                if reason:
                    line += '\n   Reason: %s' % reason
            else:
                any_posting = True
                line = '⏳ %s: %s' % (media, lp_state.capitalize())

            lines.append(line)

        summary = '\n'.join(lines) if lines else None

        if any_posting:
            overall = 'posting'
        elif any_posted:
            overall = 'posted'
        elif any_failed:
            overall = 'failed'
        else:
            overall = self._map_remote_state(remote_state)

        return summary, overall

    @staticmethod
    def _map_remote_state(remote_state):
        mapping = {
            'draft': 'draft', 'scheduled': 'scheduled',
            'posting': 'posting', 'posted': 'posted',
            'failed': 'failed', 'in_queue': 'posting',
        }
        return mapping.get(remote_state, 'posting')
