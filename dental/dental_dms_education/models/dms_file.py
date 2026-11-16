# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

MEDIA_TYPES = [
    ('video', 'Video'),
    ('animation_3d', '3D Animation'),
    ('image', 'Image / Infographic'),
    ('document', 'Leaflet / Document'),
]
PURPOSES = [
    ('pre_treatment', 'Before Treatment'),
    ('procedure', 'Procedure Explained'),
    ('post_care', 'Post-Treatment Care'),
    ('general', 'General Oral Health'),
]


class DmsFile(models.Model):
    """Education metadata on DMS files of the Patient Education Library (additive fields only)."""
    _inherit = 'dms.file'

    dental_doc_type = fields.Selection(selection_add=[('education', 'Patient Education Library')],
                                       ondelete={'education': 'set null'})
    dental_edu_media_type = fields.Selection(MEDIA_TYPES, string='Media Type')
    dental_edu_purpose = fields.Selection(PURPOSES, string='Purpose')
    dental_edu_lang_id = fields.Many2one('res.lang', string='Language', ondelete='set null')
    dental_edu_master_id = fields.Many2one(
        'dms.file', string='Language Version Of', index=True, ondelete='cascade',
        domain="[('dental_doc_type', '=', 'education'), ('dental_edu_master_id', '=', False), ('id', '!=', id)]",
        help='Set on a translated / dubbed version: it points to the original video.')
    dental_edu_variant_ids = fields.One2many('dms.file', 'dental_edu_master_id', string='Other Languages')
    dental_edu_product_ids = fields.Many2many(
        'product.template', 'dms_file_dental_edu_product_rel', 'file_id', 'product_id',
        string='Recommended For', domain=[('is_dental_treatment', '=', True)],
        help='Treatments for which this media is recommended (in addition to the topic treatments).')
    dental_edu_duration = fields.Char(string='Duration', help='e.g. 03:20')
    dental_edu_published = fields.Boolean(string='Available for Patients', default=True)
    dental_edu_description = fields.Text(string='Patient-facing Description')
    dental_edu_view_count = fields.Integer(string='Views', compute='_compute_dental_edu_view_count')

    @api.constrains('dental_edu_master_id')
    def _check_dental_edu_master(self):
        for rec in self.filtered('dental_edu_master_id'):
            if rec.dental_edu_master_id.dental_edu_master_id or rec.dental_edu_master_id == rec:
                raise ValidationError(_('A language version must point to an original video, not to another version.'))

    def _compute_dental_edu_view_count(self):
        data = {}
        if self.ids:
            groups = self.env['dental.education.view'].sudo()._read_group(
                [('file_id', 'in', self.ids)], ['file_id'], ['__count'])
            data = {file.id: count for file, count in groups}
        for rec in self:
            rec.dental_edu_view_count = data.get(rec.id, 0)

    # ------------------------------------------------------------------ language variants
    def _dental_edu_family(self):
        """The original video and all its language versions."""
        self.ensure_one()
        master = self.dental_edu_master_id or self
        return master | master.dental_edu_variant_ids

    def _dental_edu_for_lang(self, lang_code):
        """Best version of this media for a language code (falls back to the original)."""
        self.ensure_one()
        family = self._dental_edu_family().filtered('dental_edu_published')
        match = family.filtered(lambda f: f.dental_edu_lang_id.code == lang_code)
        if not match and lang_code:
            short = lang_code.split('_')[0]
            match = family.filtered(lambda f: (f.dental_edu_lang_id.code or '').split('_')[0] == short)
        return match[:1] or (self.dental_edu_master_id or self)

    # ------------------------------------------------------------------ streaming
    def _dental_edu_stream(self):
        """HTTP stream of the media, served from the DMS storage (supports HTTP range for video seeking)."""
        self.ensure_one()
        record = self.sudo()
        Binary = self.env['ir.binary']
        if record.attachment_id:
            stream = Binary._get_stream_from(record.attachment_id, 'raw')
        elif record.content_file:
            stream = Binary._get_stream_from(record, 'content_file', filename=record.name,
                                             mimetype=record.mimetype or None)
        else:
            stream = Binary._get_stream_from(record, 'content_binary', filename=record.name,
                                             mimetype=record.mimetype or None)
        return stream

    def _dental_edu_kind(self):
        """How the player should render the media: video / image / pdf / other."""
        self.ensure_one()
        mimetype = self.sudo().mimetype or ''
        if mimetype.startswith('video/') or self.dental_edu_media_type in ('video', 'animation_3d') \
                and not mimetype.startswith('image/'):
            return 'video'
        if mimetype.startswith('image/'):
            return 'image'
        if mimetype == 'application/pdf':
            return 'pdf'
        return 'other'

    # ------------------------------------------------------------------ actions
    def action_dental_edu_preview(self):
        self.ensure_one()
        if self.dental_doc_type != 'education':
            raise UserError(_('Only Patient Education Library media can be previewed here.'))
        self.check_access('read')
        return {'type': 'ir.actions.act_url', 'url': f'/dental/education/preview/{self.id}', 'target': 'new'}

    def action_dental_edu_views(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Viewing History - %s', self.name),
            'res_model': 'dental.education.view',
            'view_mode': 'list,pivot,graph',
            'domain': [('file_id', 'in', self._dental_edu_family().ids)],
        }
