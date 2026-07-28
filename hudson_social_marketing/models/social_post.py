# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

POST_STATE_SELECTION = [
    ('draft', 'Draft'),
    ('scheduled', 'Scheduled'),
    ('posting', 'Posting'),
    ('posted', 'Posted'),
    ('failed', 'Failed'),
]

# Per-platform validation rules
PLATFORM_RULES = {
    'twitter': {
        'label': 'Twitter / X',
        'max_chars': 280,
        'max_images': 4,
        'video': False,
        'images': True,
        'images_note': 'Max 4 images. JPG, PNG, GIF, WebP supported.',
    },
    'facebook': {
        'label': 'Facebook',
        'max_chars': 63206,
        'max_images': 10,
        'video': True,
        'images': True,
        'images_note': 'Max 10 images per post.',
    },
    'instagram': {
        'label': 'Instagram',
        'max_chars': 2200,
        'max_images': 10,
        'requires_image': True,
        'video': True,
        'images': True,
        'images_note': 'At least 1 image required. Max 10 images.',
    },
    'linkedin': {
        'label': 'LinkedIn',
        'max_chars': 3000,
        'max_images': 9,
        'video': True,
        'images': True,
        'images_note': 'Max 9 images per post.',
    },
    'youtube': {
        'label': 'YouTube',
        'max_chars': 5000,
        'max_images': 0,
        'video': True,
        'images': False,
        'images_note': 'YouTube only supports video uploads — images cannot be posted.',
    },
    'pinterest': {
        'label': 'Pinterest',
        'max_chars': 500,
        'max_images': 1,
        'requires_image': True,
        'video': False,
        'images': True,
        'images_note': '1 image required. JPG, PNG, WebP supported.',
    },
}


class HudsonSocialPost(models.Model):
    _name = 'hudson.social.post'
    _description = 'Social Media Post'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'hudson.social.connector']
    _rec_name = 'message_preview'
    _order = 'write_date desc'

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    message = fields.Text(
        string='Message',
        required=True,
        tracking=True,
        help='The text content of your social media post.',
    )
    active = fields.Boolean(default=True, string='Active')
    message_preview = fields.Char(
        string='Preview',
        compute='_compute_message_preview',
        store=True,
    )
    char_count = fields.Integer(
        string='Character Count',
        compute='_compute_char_count',
        store=False,
    )
    account_ids = fields.Many2many(
        comodel_name='hudson.social.account',
        relation='hudson_social_post_account_rel',
        column1='post_id',
        column2='account_id',
        string='Post On',
        tracking=True,
    )
    state = fields.Selection(
        selection=POST_STATE_SELECTION,
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        index=True,
    )
    scheduled_date = fields.Datetime(
        string='Scheduled Date',
        tracking=True,
        help='Date and time when the post will be published.',
    )
    published_date = fields.Datetime(
        string='Published Date',
        readonly=True,
        tracking=True,
    )

    # Attachments / media
    image_ids = fields.Many2many(
        comodel_name='ir.attachment',
        relation='hudson_social_post_attachment_rel',
        column1='post_id',
        column2='attachment_id',
        string='Images',
    )
    has_image = fields.Boolean(compute='_compute_has_image', store=True)
    image_count = fields.Integer(compute='_compute_has_image', store=True)

    # Analytics
    click_count = fields.Integer(string='Clicks', default=0, readonly=True)
    reach = fields.Integer(string='Reach', default=0, readonly=True)
    likes = fields.Integer(string='Likes', default=0, readonly=True)
    shares = fields.Integer(string='Shares', default=0, readonly=True)
    comments = fields.Integer(string='Comments', default=0, readonly=True)

    # Campaign
    campaign_id = fields.Many2one(
        comodel_name='utm.campaign',
        string='Campaign',
        ondelete='set null',
    )

    # Remote reference
    remote_id = fields.Integer(
        string='Remote ID',
        index=True,
        help='ID of this record on the remote Odoo instance.',
    )
    last_sync = fields.Datetime(string='Last Synced', readonly=True)
    sync_error = fields.Text(string='Sync Error', readonly=True)

    # Comments synced from remote social platforms
    comment_ids = fields.One2many(
        comodel_name='hudson.social.comment',
        inverse_name='post_id',
        string='Comments',
        readonly=True,
    )
    comment_count = fields.Integer(
        string='Comments',
        compute='_compute_comment_count',
        store=True,
    )

    # Validation warning messages (non-blocking, shown in form)
    validation_warnings = fields.Text(
        string='Validation Warnings',
        compute='_compute_validation_warnings',
        store=False,
    )
    has_validation_warnings = fields.Boolean(
        compute='_compute_validation_warnings',
        store=False,
    )

    # Computed
    account_count = fields.Integer(
        string='Accounts',
        compute='_compute_account_count',
        store=True,
    )
    platform_icons = fields.Char(
        string='Platforms',
        compute='_compute_platform_icons',
        store=False,
        help='Human-readable list of platforms this post targets.',
    )
    primary_platform = fields.Selection(
        selection=[
            ('facebook', 'Facebook'),
            ('twitter', 'Twitter / X'),
            ('instagram', 'Instagram'),
            ('linkedin', 'LinkedIn'),
            ('youtube', 'YouTube'),
            ('pinterest', 'Pinterest'),
            ('push_notifications', 'Push Notifications'),
            ('other', 'Other'),
            ('none', 'No Platform'),
        ],
        string='Primary Platform',
        compute='_compute_primary_platform',
        store=True,
        help='The first connected platform for grouping in the dashboard.',
    )

    # ------------------------------------------------------------------
    # SQL Constraints
    # ------------------------------------------------------------------
    _sql_constraints = [
        ('remote_id_unique', 'UNIQUE(remote_id)', 'Each remote post must be unique.'),
    ]

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends('message')
    def _compute_message_preview(self):
        for rec in self:
            if rec.message:
                rec.message_preview = (rec.message[:80] + '…') if len(rec.message) > 80 else rec.message
            else:
                rec.message_preview = _('(No message)')

    @api.depends('message')
    def _compute_char_count(self):
        for rec in self:
            rec.char_count = len(rec.message or '')

    @api.depends('image_ids')
    def _compute_has_image(self):
        for rec in self:
            rec.image_count = len(rec.image_ids)
            rec.has_image = bool(rec.image_ids)

    @api.depends('account_ids')
    def _compute_account_count(self):
        for rec in self:
            rec.account_count = len(rec.account_ids)

    @api.depends('comment_ids')
    def _compute_comment_count(self):
        for rec in self:
            rec.comment_count = len(rec.comment_ids)

    @api.depends('account_ids.media_type')
    def _compute_platform_icons(self):
        """Return a human-readable list of platforms (e.g. 'Twitter/X · LinkedIn').
        This is displayed in the right-panel preview header.
        """
        label_map = {
            'facebook': 'Facebook',
            'twitter': 'Twitter/X',
            'instagram': 'Instagram',
            'linkedin': 'LinkedIn',
            'youtube': 'YouTube',
            'pinterest': 'Pinterest',
            'push_notifications': 'Push',
            'other': 'Other',
        }
        for rec in self:
            seen = []
            for acc in rec.account_ids:
                lbl = label_map.get(acc.media_type, acc.media_type or 'Other')
                if lbl not in seen:
                    seen.append(lbl)
            rec.platform_icons = ' · '.join(seen) if seen else ''

    @api.depends('account_ids', 'account_ids.media_type')
    def _compute_primary_platform(self):
        for rec in self:
            if rec.account_ids:
                rec.primary_platform = rec.account_ids[0].media_type or 'other'
            else:
                rec.primary_platform = 'none'

    @api.depends('message', 'account_ids', 'image_ids', 'account_ids.media_type')
    def _compute_validation_warnings(self):
        """Compute per-platform warnings shown inline in the form (non-blocking)."""
        for rec in self:
            warnings = []
            msg = rec.message or ''
            msg_len = len(msg)
            image_count = len(rec.image_ids)
            platform_types = set(rec.account_ids.mapped('media_type'))

            for ptype in platform_types:
                rules = PLATFORM_RULES.get(ptype)
                if not rules:
                    continue
                label = rules['label']

                # Character limit check
                max_c = rules.get('max_chars')
                if max_c and msg_len > max_c:
                    warnings.append(
                        f"⚠️ {label}: Message is {msg_len} characters — limit is {max_c:,}. "
                        f"Please shorten by {msg_len - max_c} characters."
                    )

                # Image not supported
                if image_count > 0 and not rules.get('images', True):
                    warnings.append(
                        f"⚠️ {label}: Images are not supported. "
                        f"Images will be ignored when posting to {label}."
                    )

                # Image required
                if rules.get('requires_image') and image_count == 0:
                    warnings.append(
                        f"⚠️ {label}: At least one image is required for {label} posts."
                    )

                # Too many images
                max_img = rules.get('max_images', 0)
                if max_img and image_count > max_img:
                    warnings.append(
                        f"⚠️ {label}: Max {max_img} image(s) allowed — you have {image_count}. "
                        f"Only the first {max_img} will be used."
                    )

            rec.validation_warnings = '\n'.join(warnings) if warnings else ''
            rec.has_validation_warnings = bool(warnings)

    # ------------------------------------------------------------------
    # Hard-blocking validation (runs on save / publish)
    # ------------------------------------------------------------------

    def _validate_platform_rules(self):
        """Raise ValidationError if any platform rule is critically violated.
        Call this before publishing or syncing to the remote.
        """
        for rec in self:
            msg = rec.message or ''
            msg_len = len(msg)
            image_count = len(rec.image_ids)
            platform_types = set(rec.account_ids.mapped('media_type'))

            if not platform_types:
                raise ValidationError(_(
                    "Please select at least one platform to post on."
                ))

            for ptype in platform_types:
                rules = PLATFORM_RULES.get(ptype)
                if not rules:
                    continue
                label = rules['label']

                # Character limit — hard block
                max_c = rules.get('max_chars')
                if max_c and msg_len > max_c:
                    raise ValidationError(_(
                        "%(label)s: Your message is %(count)d characters. "
                        "The maximum allowed for %(label)s is %(max)d characters. "
                        "Please shorten your message by %(over)d characters.",
                        label=label,
                        count=msg_len,
                        max=max_c,
                        over=msg_len - max_c,
                    ))

                # Image required — hard block
                if rules.get('requires_image') and image_count == 0:
                    raise ValidationError(_(
                        "%(label)s requires at least one image. "
                        "Please attach an image before publishing.",
                        label=label,
                    ))

    # ------------------------------------------------------------------
    # Business actions
    # ------------------------------------------------------------------

    def action_publish_now(self):
        """Validate rules then open the publish wizard."""
        self.ensure_one()
        self._validate_platform_rules()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Publish Post'),
            'res_model': 'hudson.social.post.publish.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_post_id': self.id,
                'default_publish_type': 'now',
            },
        }

    def action_schedule(self):
        """Validate rules then open the publish wizard in schedule mode."""
        self.ensure_one()
        self._validate_platform_rules()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Schedule Post'),
            'res_model': 'hudson.social.post.publish.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_post_id': self.id,
                'default_publish_type': 'schedule',
            },
        }

    def action_set_draft(self):
        self.write({'state': 'draft'})

    def action_sync_to_remote(self):
        """Push the current post to the remote Odoo instance (create or update),
        including image attachments via the correct remote model chain.

        Per the remote social module schema (technical guide):
          social.post.image_ids  →  M2M to social.post.image
          social.post.image:
            - attachment_id  (required M2O → ir.attachment)
            - raw            (binary — the actual image data)
            - name, mimetype, file_size, sequence
        """
        self.ensure_one()
        self._validate_platform_rules()
        remote_account_ids = self._resolve_remote_account_ids()

        vals = {
            'message': self.message or '',
            'facebook_message': self.message or '',
            'twitter_message': self.message or '',
            'instagram_message': self.message or '',
            'linkedin_message': self.message or '',
        }
        if remote_account_ids:
            vals['account_ids'] = [[6, 0, remote_account_ids]]

        try:
            if self.remote_id:
                # Update existing remote post (message + accounts only;
                # do not replace images on an already-synced post)
                self._social_write('social.post', [self.remote_id], vals)
                _logger.info("Updated remote post id=%s", self.remote_id)
            else:
                # Step 1: Create the remote post without images first
                remote_id = self._social_create('social.post', vals)
                self.write({'remote_id': remote_id, 'sync_error': False})
                _logger.info("Created remote post id=%s", remote_id)

                # Step 2: Upload images as social.post.image records and link them
                if self.image_ids:
                    remote_image_ids = self._upload_images_to_remote(remote_post_id=remote_id)
                    if remote_image_ids:
                        img_cmd = [[6, 0, remote_image_ids]]
                        self._social_write(
                            'social.post', [remote_id],
                            {
                                'image_ids': img_cmd,
                                'facebook_image_ids': img_cmd,
                                'twitter_image_ids': img_cmd,
                                'instagram_image_ids': img_cmd,
                                'linkedin_image_ids': img_cmd,
                            }
                        )
                        _logger.info(
                            "Linked %d image(s) to remote post id=%s",
                            len(remote_image_ids), remote_id,
                        )

            self.write({'last_sync': fields.Datetime.now(), 'sync_error': False})
        except UserError as e:
            self.write({'sync_error': str(e)})
            raise

    def _upload_images_to_remote(self, remote_post_id=None):
        """Upload local images to the remote Odoo using the social.post.image model chain.

        Per the technical guide, the remote Odoo social module uses a dedicated
        `social.post.image` model whose `image_ids` M2M field links to `social.post`.

        Each `social.post.image` record requires:
          - attachment_id  (M2O to ir.attachment, required)
          - raw            (binary data)
          - name, mimetype, sequence

        Compression strategy:
          - Keep original format (PNG stays PNG, JPEG stays JPEG).
          - For PNG: use optimize=True + reduce palette to compress.
          - For JPEG: reduce quality until within size limit.
          - Only convert PNG->JPEG as absolute last resort if PNG is still too large.
          - Preserve aspect ratio; resize DOWN if image > MAX_DIM.
          - Do NOT resize below MIN_DIM (LinkedIn requires >= 200px).

        :param remote_post_id: ID of the already-created remote social.post record.
        :returns: list of remote social.post.image record IDs
        """
        import base64 as _base64
        import io as _io

        PLATFORM_IMAGE_LIMITS = {
            'twitter':   5 * 1024 * 1024,   # Twitter allows up to 5 MB
            'linkedin':  5 * 1024 * 1024,   # LinkedIn: up to 5 MB
            'facebook':  4 * 1024 * 1024,
            'instagram': 8 * 1024 * 1024,
            'pinterest': 4 * 1024 * 1024,
            'youtube':   None,
        }
        MAX_DIM = 4096   # px on longest side (Twitter max)
        MIN_DIM = 200    # px minimum (LinkedIn requirement)

        def compress_b64(raw_b64, max_bytes, name='image'):
            """Smart-compress a base64 image preserving format where possible.

            Returns (compressed_b64, final_name, final_mime).
            """
            try:
                from PIL import Image as _PIL
            except ImportError:
                _logger.warning("Pillow not installed — skipping image compression.")
                ext = (name.rsplit('.', 1)[-1] if '.' in name else 'jpg').lower()
                mime = 'image/png' if ext == 'png' else 'image/jpeg'
                return raw_b64, name, mime

            try:
                raw_bytes = _base64.b64decode(raw_b64)
                original_size = len(raw_bytes)
                ext = (name.rsplit('.', 1)[-1] if '.' in name else 'jpg').lower()
                is_png = ext == 'png'
                is_gif = ext == 'gif'

                img = _PIL.open(_io.BytesIO(raw_bytes))
                orig_mode = img.mode
                orig_format = img.format or ('PNG' if is_png else 'JPEG')
                _logger.info(
                    "Processing '%s': %dx%d %s, %d bytes",
                    name, img.width, img.height, orig_format, original_size,
                )

                # ── 1. Resize DOWN if oversized ──────────────────────────────
                w, h = img.size
                if max(w, h) > MAX_DIM:
                    ratio = MAX_DIM / max(w, h)
                    new_w, new_h = max(int(w * ratio), MIN_DIM), max(int(h * ratio), MIN_DIM)
                    img = img.resize((new_w, new_h), _PIL.LANCZOS)

                # ── 2. Upscale if too small (LinkedIn minimum) ────────────────
                w, h = img.size
                if min(w, h) < MIN_DIM:
                    ratio = MIN_DIM / min(w, h)
                    img = img.resize((int(w * ratio), int(h * ratio)), _PIL.LANCZOS)

                # ── 3. If no size limit or already small enough, keep original ─
                if not max_bytes or original_size <= max_bytes:
                    buf = _io.BytesIO()
                    save_fmt = 'PNG' if is_png else 'JPEG'
                    if save_fmt == 'JPEG' and img.mode not in ('RGB', 'L'):
                        img = img.convert('RGB')
                    kw = {'format': save_fmt, 'optimize': True}
                    if save_fmt == 'JPEG':
                        kw['quality'] = 92
                    img.save(buf, **kw)
                    out = buf.getvalue()
                    mime = 'image/png' if is_png else 'image/jpeg'
                    return _base64.b64encode(out).decode(), name, mime

                target = max_bytes

                # ── 4a. Try PNG compression (for PNG originals) ───────────────
                if is_png:
                    for compress_level in (7, 8, 9):
                        buf = _io.BytesIO()
                        # Keep original mode for PNG (preserves transparency, B&W)
                        img.save(buf, format='PNG', optimize=True, compress_level=compress_level)
                        out = buf.getvalue()
                        if len(out) <= target:
                            _logger.info(
                                "PNG-compressed '%s': %d -> %d bytes (level=%d)",
                                name, original_size, len(out), compress_level,
                            )
                            return _base64.b64encode(out).decode(), name, 'image/png'

                    # PNG still too large — try halving dimensions
                    small = img.resize((img.width // 2, img.height // 2), _PIL.LANCZOS)
                    if min(small.size) >= MIN_DIM:
                        buf = _io.BytesIO()
                        small.save(buf, format='PNG', optimize=True, compress_level=9)
                        out = buf.getvalue()
                        if len(out) <= target:
                            _logger.info("Halved PNG '%s': %d -> %d bytes", name, original_size, len(out))
                            return _base64.b64encode(out).decode(), name, 'image/png'

                    # Last resort: convert PNG to JPEG (only for non-QR-code-like images)
                    if img.mode in ('RGBA', 'P', 'LA'):
                        # Create white background
                        bg = _PIL.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        if 'A' in img.getbands():
                            bg.paste(img, mask=img.split()[-1])
                        else:
                            bg.paste(img)
                        img_rgb = bg
                    else:
                        img_rgb = img.convert('RGB')

                    for quality in (85, 75, 65, 55, 40):
                        buf = _io.BytesIO()
                        img_rgb.save(buf, format='JPEG', quality=quality, optimize=True)
                        out = buf.getvalue()
                        if len(out) <= target:
                            jpg_name = name.rsplit('.', 1)[0] + '.jpg'
                            _logger.info(
                                "Converted PNG->JPEG '%s': %d -> %d bytes (q=%d)",
                                name, original_size, len(out), quality,
                            )
                            return _base64.b64encode(out).decode(), jpg_name, 'image/jpeg'

                # ── 4b. JPEG compression ───────────────────────────────────────
                if img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')
                for quality in (85, 75, 65, 55, 40, 30):
                    buf = _io.BytesIO()
                    img.save(buf, format='JPEG', quality=quality, optimize=True)
                    out = buf.getvalue()
                    if len(out) <= target:
                        jpg_name = name if name.lower().endswith('.jpg') else (name.rsplit('.', 1)[0] + '.jpg')
                        _logger.info(
                            "JPEG-compressed '%s': %d -> %d bytes (q=%d)",
                            name, original_size, len(out), quality,
                        )
                        return _base64.b64encode(out).decode(), jpg_name, 'image/jpeg'

                # Aggressive resize as last resort
                img = img.resize((img.width // 2, img.height // 2), _PIL.LANCZOS)
                buf = _io.BytesIO()
                img.save(buf, format='JPEG', quality=40, optimize=True)
                out = buf.getvalue()
                jpg_name = name.rsplit('.', 1)[0] + '.jpg'
                _logger.info("Aggressively resized '%s': %d -> %d bytes", name, original_size, len(out))
                return _base64.b64encode(out).decode(), jpg_name, 'image/jpeg'

            except Exception as exc:
                _logger.warning("Image compression error for '%s': %s", name, exc)
                ext = (name.rsplit('.', 1)[-1] if '.' in name else 'jpg').lower()
                mime = 'image/png' if ext == 'png' else 'image/jpeg'
                return raw_b64, name, mime

        supported = {'facebook', 'twitter', 'instagram', 'linkedin', 'youtube'}
        account_types = set(self.account_ids.mapped('media_type'))
        if not account_types & supported:
            _logger.info("No supported image platform — skipping image upload.")
            return []

        # Determine the tightest size limit across all selected platforms
        platform_limits = [
            PLATFORM_IMAGE_LIMITS.get(pt)
            for pt in account_types
            if PLATFORM_IMAGE_LIMITS.get(pt) is not None
        ]
        max_bytes = min(platform_limits) if platform_limits else 5 * 1024 * 1024

        remote_image_ids = []
        for seq, attachment in enumerate(self.image_ids, start=1):
            if not attachment.datas:
                _logger.warning("Skipping attachment '%s' — no binary data.", attachment.name)
                continue

            att_name = attachment.name or 'image.jpg'
            att_mime = attachment.mimetype or 'image/jpeg'

            # Get raw b64, normalise to str
            raw_b64 = (
                attachment.datas.decode('utf-8')
                if isinstance(attachment.datas, bytes)
                else attachment.datas
            )

            # ── Compress / reformat to meet platform requirements ─────────────
            compressed_b64, att_name, att_mime = compress_b64(raw_b64, max_bytes, att_name)

            try:
                # ── Step 1: Create ir.attachment on the remote ────────────────
                att_vals = {
                    'name': att_name,
                    'raw': compressed_b64,
                    'mimetype': att_mime,
                    'res_model': 'social.post',
                    'type': 'binary',
                }
                if remote_post_id:
                    att_vals['res_id'] = remote_post_id
                remote_att_id = self._social_create('ir.attachment', att_vals)
                _logger.info(
                    "Created remote ir.attachment id=%s for image '%s'",
                    remote_att_id, att_name,
                )

                # ── Step 2: Create social.post.image linking to that attachment ──
                img_vals = {
                    'attachment_id': remote_att_id,  # required FK to ir.attachment
                    'name': att_name,
                    'mimetype': att_mime,
                    'sequence': seq,
                    'raw': compressed_b64,
                }
                remote_img_id = self._social_create('social.post.image', img_vals)
                _logger.info(
                    "Created remote social.post.image id=%s (attachment=%s) for '%s'",
                    remote_img_id, remote_att_id, att_name,
                )
                remote_image_ids.append(remote_img_id)

            except UserError as e:
                _logger.warning("Failed to upload image '%s': %s", att_name, e)
                # Continue with remaining images — don't abort entire sync

        return remote_image_ids


        """Upload local images to the remote Odoo using the social.post.image model chain.

        Per the technical guide, the remote Odoo social module uses a dedicated
        `social.post.image` model whose `image_ids` M2M field links to `social.post`.

        Each `social.post.image` record requires:
          - attachment_id  (M2O → ir.attachment, required)
          - raw            (binary data)
          - name, mimetype, sequence

        Images are automatically compressed before upload to avoid API-level
        "image too large" errors from LinkedIn, Twitter/X, etc.

        Correct 3-step flow per image:
          1. Compress image to platform size limit
          2. Create ir.attachment on remote  → remote_att_id
          3. Create social.post.image with attachment_id=remote_att_id + raw data
          4. Return list of social.post.image IDs to link via social.post.image_ids

        :param remote_post_id: ID of the already-created remote social.post record.
        :returns: list of remote social.post.image record IDs
        """
        import base64 as _base64
        import io as _io

        PLATFORM_IMAGE_LIMITS = {
            'twitter':   4 * 1024 * 1024,
            'linkedin':  3 * 1024 * 1024,   # 3 MB to be safe with LinkedIn
            'facebook':  4 * 1024 * 1024,
            'instagram': 8 * 1024 * 1024,
            'pinterest': 4 * 1024 * 1024,
            'youtube':   None,
        }
        MAX_DIM = 1920  # px on the longest side

        def compress_b64(raw_b64, max_bytes, name='image'):
            """Compress base64 image if it exceeds max_bytes. Returns compressed b64 str."""
            try:
                from PIL import Image as _PIL
            except ImportError:
                return raw_b64

            try:
                raw_bytes = _base64.b64decode(raw_b64)
                original_size = len(raw_bytes)
                if max_bytes and original_size <= max_bytes:
                    return raw_b64  # already small enough

                img = _PIL.open(_io.BytesIO(raw_bytes))
                if img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')

                # Resize if too large in pixels
                w, h = img.size
                if max(w, h) > MAX_DIM:
                    ratio = MAX_DIM / max(w, h)
                    img = img.resize((int(w * ratio), int(h * ratio)), _PIL.LANCZOS)

                target = max_bytes or (4 * 1024 * 1024)
                for quality in (85, 75, 65, 50, 40):
                    buf = _io.BytesIO()
                    img.save(buf, format='JPEG', quality=quality, optimize=True)
                    compressed = buf.getvalue()
                    if len(compressed) <= target:
                        _logger.info(
                            "Compressed '%s': %d → %d bytes (q=%d)",
                            name, original_size, len(compressed), quality,
                        )
                        return _base64.b64encode(compressed).decode('utf-8')

                # Aggressive resize as last resort
                img = img.resize((img.width // 2, img.height // 2), _PIL.LANCZOS)
                buf = _io.BytesIO()
                img.save(buf, format='JPEG', quality=40, optimize=True)
                compressed = buf.getvalue()
                _logger.info(
                    "Aggressively resized '%s': %d → %d bytes",
                    name, original_size, len(compressed),
                )
                return _base64.b64encode(compressed).decode('utf-8')

            except Exception as exc:
                _logger.warning("Image compression error for '%s': %s", name, exc)
                return raw_b64

        supported = {'facebook', 'twitter', 'instagram', 'linkedin', 'youtube'}
        account_types = set(self.account_ids.mapped('media_type'))
        if not account_types & supported:
            _logger.info("No supported image platform — skipping image upload.")
            return []

        # Determine the tightest size limit across all selected platforms
        platform_limits = [
            PLATFORM_IMAGE_LIMITS.get(pt)
            for pt in account_types
            if PLATFORM_IMAGE_LIMITS.get(pt) is not None
        ]
        max_bytes = min(platform_limits) if platform_limits else 4 * 1024 * 1024

        remote_image_ids = []
        for seq, attachment in enumerate(self.image_ids, start=1):
            if not attachment.datas:
                _logger.warning("Skipping attachment '%s' — no binary data.", attachment.name)
                continue

            att_name = attachment.name or 'image.jpg'
            att_mime = attachment.mimetype or 'image/jpeg'

            # Get raw b64, normalise to str
            raw_b64 = (
                attachment.datas.decode('utf-8')
                if isinstance(attachment.datas, bytes)
                else attachment.datas
            )

            # ── Compress image to meet platform size requirements ──────────
            # Always compress to JPEG for maximum compatibility with social APIs
            compressed_b64 = compress_b64(raw_b64, max_bytes, att_name)
            # JPEG name after compression
            if att_name.lower().endswith(('.png', '.gif', '.webp', '.bmp', '.tiff')):
                att_name = att_name.rsplit('.', 1)[0] + '.jpg'
                att_mime = 'image/jpeg'

            try:
                # ── Step 1: Create ir.attachment on the remote ──────────────
                att_vals = {
                    'name': att_name,
                    'datas': compressed_b64,
                    'mimetype': att_mime,
                    'res_model': 'social.post',
                    'type': 'binary',
                }
                if remote_post_id:
                    att_vals['res_id'] = remote_post_id
                remote_att_id = self._social_create('ir.attachment', att_vals)
                _logger.info(
                    "Created remote ir.attachment id=%s for image '%s'",
                    remote_att_id, att_name,
                )

                # ── Step 2: Create social.post.image linking to that attachment ──
                img_vals = {
                    'attachment_id': remote_att_id,  # required FK to ir.attachment
                    'name': att_name,
                    'mimetype': att_mime,
                    'sequence': seq,
                    'raw': compressed_b64,           # compressed binary on the post.image record
                }
                remote_img_id = self._social_create('social.post.image', img_vals)
                _logger.info(
                    "Created remote social.post.image id=%s (attachment=%s) for '%s'",
                    remote_img_id, remote_att_id, att_name,
                )
                remote_image_ids.append(remote_img_id)

            except UserError as e:
                _logger.warning("Failed to upload image '%s': %s", att_name, e)
                # Continue with remaining images — don't abort entire sync

        return remote_image_ids



    def action_upload_images(self):
        """Button action: upload images to remote and show result notification."""
        self.ensure_one()
        if not self.image_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Images'),
                    'message': _('Please attach images before uploading.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        if not self.remote_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Post Not Synced'),
                    'message': _(
                        'Publish or sync the post first so a remote record '
                        'exists before uploading images.'
                    ),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        uploaded = self._upload_images_to_remote(remote_post_id=self.remote_id)
        if uploaded:
            try:
                existing = self._social_execute(
                    'social.post', 'read', [[self.remote_id]], fields=['image_ids']
                )
                existing_ids = existing[0].get('image_ids', []) if existing else []
                all_ids = list(set(existing_ids + uploaded))
                self._social_write(
                    'social.post', [self.remote_id],
                    {'image_ids': [[6, 0, all_ids]]}
                )
            except UserError as e:
                _logger.warning("Could not link uploaded images to remote post: %s", e)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Images Uploaded'),
                'message': _('%d image(s) uploaded to the remote Odoo instance.') % len(uploaded),
                'type': 'success' if uploaded else 'warning',
                'sticky': False,
            },
        }

    def _resolve_remote_account_ids(self):
        """Return remote account IDs corresponding to our local account_ids."""
        remote_ids = []
        for acc in self.account_ids:
            if acc.remote_id:
                remote_ids.append(acc.remote_id)
        return remote_ids

    def _push_state_to_remote(self, action):
        """Call a button/method action on the remote post."""
        self.ensure_one()
        if not self.remote_id:
            raise UserError(_("This post has not been synced to the remote server yet."))
        return self._social_execute(
            'social.post', action, [[self.remote_id]]
        )

    def action_check_remote_status(self):
        """Pull the latest state from the remote Enterprise instance and update
        local record.  Reads social.live.post records to get per-platform detail
        including failure_reason (from the technical guide schema).
        """
        self.ensure_one()
        if not self.remote_id:
            raise UserError(_(
                "This post has not been synced to remote yet. "
                "Publish it first to get a remote ID."
            ))

        # Read parent post state + live_post_ids
        try:
            remote_data = self._social_execute(
                'social.post', 'read',
                [[self.remote_id]],
                fields=['state', 'live_post_ids', 'published_date'],
            )
        except UserError as e:
            raise UserError(_("Could not reach the remote server:\n%s") % str(e))

        if not remote_data:
            raise UserError(_("Remote post id=%s not found.") % self.remote_id)

        remote_state = remote_data[0].get('state', 'draft')
        live_post_ids = remote_data[0].get('live_post_ids') or []
        published_date = remote_data[0].get('published_date') or False

        # Map remote state to local state
        state_map = {
            'draft': 'draft', 'scheduled': 'scheduled',
            'posting': 'posting', 'posted': 'posted',
            'failed': 'failed', 'in_queue': 'posting',
        }
        local_state = state_map.get(remote_state, 'posting')

        write_vals = {
            'state': local_state,
            'last_sync': fields.Datetime.now(),
            'sync_error': False,
        }
        if published_date:
            write_vals['published_date'] = published_date
        self.write(write_vals)

        # Read live post details for notification
        lines = []
        if live_post_ids:
            try:
                live_details = self._social_execute(
                    'social.live.post', 'read',
                    [live_post_ids],
                    fields=['state', 'failure_reason', 'live_post_link', 'media_type'],
                )
                for lp in (live_details or []):
                    lp_state = lp.get('state', 'posting')
                    media = (lp.get('media_type') or 'unknown').capitalize()
                    link = lp.get('live_post_link') or ''
                    reason = lp.get('failure_reason') or ''
                    if lp_state == 'posted':
                        line = '✅ %s: Published' % media
                        if link:
                            line += ' — %s' % link
                    elif lp_state == 'failed':
                        line = '❌ %s: Failed' % media
                        if reason:
                            line += '\n   %s' % reason
                    else:
                        line = '⏳ %s: %s' % (media, lp_state.capitalize())
                    lines.append(line)
            except UserError as e:
                _logger.warning("Could not read live post details: %s", e)

        message = '\n'.join(lines) if lines else (
            _('Remote post state: %s') % remote_state.upper()
        )

        notif_type = (
            'success' if local_state == 'posted'
            else 'danger' if local_state == 'failed'
            else 'info'
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Remote Status Updated'),
                'message': message,
                'type': notif_type,
                'sticky': local_state in ('failed',),
            },
        }

    def action_sync_comments(self):
        """Fetch comments from the remote Enterprise social instance.

        Flow (based on API introspection):
          social.post.live_post_ids
            -> social.live.post: twitter_tweet_id / linkedin_post_id / facebook_post_id
            -> social.stream.post: search by tweet_id / post_id
            -> Per platform, read comment counts + use get_comments method

        Comments themselves are fetched live from social media via the Enterprise
        connector. We store them locally as hudson.social.comment records.
        """
        self.ensure_one()
        if not self.remote_id:
            raise UserError(_(
                "This post has not been synced to remote yet. "
                "Publish it first before syncing comments."
            ))

        try:
            # Step 1: Get live posts
            post_data = self._social_execute(
                'social.post', 'read', [[self.remote_id]],
                fields=['live_post_ids'],
            )
        except UserError as e:
            raise UserError(_("Could not reach remote server: %s") % str(e))

        live_post_ids = (post_data[0].get('live_post_ids') or []) if post_data else []
        if not live_post_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Live Posts'),
                    'message': _(
                        'This post has not been published on any platform yet. '
                        'Publish it first, then sync comments.'
                    ),
                    'type': 'warning',
                    'sticky': False,
                },
            }

        # Step 2: Read live posts to find platform-specific post IDs
        live_posts = self._social_execute(
            'social.live.post', 'read', [live_post_ids],
            fields=['media_type', 'twitter_tweet_id', 'linkedin_post_id', 'facebook_post_id', 'instagram_post_id'],
        ) or []

        # Step 3: Find stream posts that match our live posts
        # Twitter: search by twitter_tweet_id
        # LinkedIn/Facebook: search by account_id and recency
        tweet_ids = [
            str(lp['twitter_tweet_id'])
            for lp in live_posts
            if lp.get('media_type') == 'twitter' and lp.get('twitter_tweet_id')
        ]
        li_post_ids = [
            lp.get('linkedin_post_id')
            for lp in live_posts
            if lp.get('media_type') == 'linkedin' and lp.get('linkedin_post_id')
        ]
        fb_post_ids = [
            str(lp['facebook_post_id'])
            for lp in live_posts
            if lp.get('media_type') == 'facebook' and lp.get('facebook_post_id')
        ]
        ig_post_ids = [
            str(lp['instagram_post_id'])
            for lp in live_posts
            if lp.get('media_type') == 'instagram' and lp.get('instagram_post_id')
        ]

        # Force refresh all streams on remote to fetch the latest comments/posts
        try:
            streams = self._social_execute('social.stream', 'search_read', [[]], fields=['id'])
            if streams:
                stream_ids = [s['id'] for s in streams]
                self._social_execute('social.stream', 'action_refresh', [stream_ids])
        except Exception as e:
            _logger.warning("Failed to refresh social streams on remote: %s", e)

        stream_posts = []
        if tweet_ids:
            tw_sp = self._social_execute(
                'social.stream.post', 'search_read',
                [[['twitter_tweet_id', 'in', tweet_ids]]],
                fields=['id', 'media_type', 'twitter_comments_count',
                        'linkedin_comments_count', 'facebook_comments_count',
                        'twitter_tweet_id'],
            ) or []
            stream_posts.extend(tw_sp)
        if li_post_ids:
            li_sp = self._social_execute(
                'social.stream.post', 'search_read',
                [[['linkedin_post_urn', 'in', li_post_ids]]],
                fields=['id', 'media_type', 'linkedin_comments_count',
                        'linkedin_post_urn'],
            ) or []
            stream_posts.extend(li_sp)
        if fb_post_ids:
            fb_sp = self._social_execute(
                'social.stream.post', 'search_read',
                [[['facebook_post_id', 'in', fb_post_ids]]],
                fields=['id', 'media_type', 'facebook_comments_count', 'facebook_post_id'],
            ) or []
            stream_posts.extend(fb_sp)
        if ig_post_ids:
            ig_sp = self._social_execute(
                'social.stream.post', 'search_read',
                [[['instagram_post_id', 'in', ig_post_ids]]],
                fields=['id', 'media_type', 'instagram_comments_count', 'instagram_post_id'],
            ) or []
            stream_posts.extend(ig_sp)

        if not stream_posts:
            # No stream posts found — return comment count info from live posts only
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Stream Posts Found'),
                    'message': _(
                        'No social media stream posts were found for this post. '
                        'Ensure the social streams are configured and synced on the Enterprise instance.'
                    ),
                    'type': 'info',
                    'sticky': False,
                },
            }

        # Step 4: For each stream post, call get_comments to fetch actual comments
        Comment = self.env['hudson.social.comment']
        existing_keys = set(self.comment_ids.mapped('remote_key'))
        new_count = 0
        total_count = 0

        for sp in stream_posts:
            sp_id = sp['id']
            platform = sp.get('media_type', 'other')
            comments_raw = []

            if platform == 'twitter' and sp.get('twitter_tweet_id'):
                try:
                    tw_replies = self._social_execute(
                        'social.stream.post', 'search_read',
                        [[
                            ['twitter_conversation_id', '=', sp['twitter_tweet_id']],
                            ['id', '!=', sp_id]
                        ]],
                        fields=['id', 'message', 'author_name', 'published_date', 'twitter_tweet_id']
                    ) or []
                    for rep in tw_replies:
                        comments_raw.append({
                            'id': rep.get('twitter_tweet_id'),
                            'message': rep.get('message'),
                            'from': {'name': rep.get('author_name')},
                            'created_time': rep.get('published_date'),
                        })
                except Exception as e:
                    _logger.warning("Failed to fetch Twitter replies for stream post %s: %s", sp_id, e)
            else:
                try:
                    result = self._social_execute(
                        'social.stream.post', 'get_comments',
                        [[sp_id]],
                    )
                    if result and isinstance(result, dict):
                        comments_raw = result.get('comments', [])
                    elif result and isinstance(result, list):
                        comments_raw = result
                except Exception as e:
                    _logger.warning("get_comments failed for stream post %s: %s", sp_id, e)

            for cmt in comments_raw:
                total_count += 1
                # Build a unique key
                cmt_id = (
                    cmt.get('id')
                    or cmt.get('comment_id')
                    or cmt.get('twitter_comment_id')
                    or cmt.get('linkedin_comment_urn')
                    or ''
                )
                remote_key = '%s:%s' % (platform, str(cmt_id))

                if remote_key in existing_keys:
                    continue  # already have it

                vals = {
                    'post_id': self.id,
                    'author_name': (
                        cmt.get('author_name')
                        or cmt.get('from', {}).get('name')
                        or _('Unknown')
                    ),
                    'author_avatar_url': (
                        cmt.get('author_image_url')
                        or cmt.get('profile_image_url')
                        or ''
                    ),
                    'message': (
                        cmt.get('message')
                        or cmt.get('text', {}).get('text')
                        or ''
                    ),
                    'published_date': cmt.get('created_at') or cmt.get('published_date'),
                    'platform': platform if platform in (
                        'twitter', 'linkedin', 'facebook', 'instagram', 'youtube'
                    ) else 'other',
                    'likes_count': cmt.get('likes_count') or cmt.get('likes') or 0,
                    'twitter_screen_name': cmt.get('author_screen_name') or '',
                    'remote_key': remote_key,
                }
                Comment.create(vals)
                existing_keys.add(remote_key)
                new_count += 1

        msg = _('%d comment(s) found. %d new comment(s) saved.') % (total_count, new_count)
        notif_type = 'success' if new_count > 0 else 'info'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Comments Synced'),
                'message': msg,
                'type': notif_type,
                'sticky': False,
            },
        }


    # ------------------------------------------------------------------
    # Sync from remote
    # ------------------------------------------------------------------

    @api.model
    def sync_from_remote(self):
        """Pull social.post records from the remote Odoo instance."""
        _logger.info("Syncing social posts from remote...")
        try:
            remote_posts = self._social_search_read(
                'social.post',
                domain=[],
                fields=['id', 'message', 'state', 'scheduled_date', 'published_date',
                        'account_ids', 'click_count', 'engagement'],
                limit=500,
                order='id desc',
            )
        except UserError as e:
            _logger.error("Failed to sync social posts: %s", e)
            return False

        SocialAccount = self.env['hudson.social.account']

        for remote in remote_posts:
            rid = remote.get('id')
            existing = self.search([('remote_id', '=', rid)], limit=1)

            # Map remote account IDs to local records
            remote_acc_ids = remote.get('account_ids') or []
            local_accounts = SocialAccount.search([('remote_id', 'in', remote_acc_ids)])

            state = remote.get('state') or 'draft'
            if state not in dict(POST_STATE_SELECTION):
                state = 'draft'

            vals = {
                'message': remote.get('message') or '',
                'state': state,
                'scheduled_date': remote.get('scheduled_date') or False,
                'published_date': remote.get('published_date') or False,
                'click_count': remote.get('click_count') or 0,
                'reach': remote.get('engagement') or 0,
                'remote_id': rid,
                'last_sync': fields.Datetime.now(),
                'sync_error': False,
            }

            if existing:
                existing.write(vals)
                existing.write({'account_ids': [(6, 0, local_accounts.ids)]})
            else:
                post = self.create(vals)
                post.write({'account_ids': [(6, 0, local_accounts.ids)]})

        _logger.info("Social posts sync complete — %d records processed.", len(remote_posts))
        return True

    # ------------------------------------------------------------------
    # Scheduled action entry point
    # ------------------------------------------------------------------

    @api.model
    def action_sync_all(self):
        """Called by the ir.cron scheduled action — syncs accounts then posts.
        Uses sudo() so it works regardless of the calling user's group membership.
        """
        _logger.info("=== Hudson Social Marketing: Starting full sync ===")
        self.env['hudson.social.account'].sudo().sync_from_remote()
        self.sudo().sync_from_remote()
        self.env['hudson.social.stream.post'].sudo().sync_from_remote()

        # Auto-sync comments for all posted posts with a remote ID
        posted_posts = self.sudo().search([('state', '=', 'posted'), ('remote_id', '!=', False)])
        for post in posted_posts:
            try:
                post.action_sync_comments()
            except Exception as e:
                _logger.warning("Failed to auto-sync comments for post %s: %s", post.id, e)

        _logger.info("=== Hudson Social Marketing: Full sync complete ===")
