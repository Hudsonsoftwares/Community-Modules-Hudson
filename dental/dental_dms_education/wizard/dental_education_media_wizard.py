# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.dental_dms.models.dental_dms_service import clean_name
from odoo.addons.dms.tools import file as dms_file_tools

from ..models.dms_file import MEDIA_TYPES, PURPOSES

EDU_MANAGER_GROUPS = ('dental_base.group_dental_manager', 'dental_base.group_dental_admin', 'dms.group_dms_manager')


class DentalEducationMediaWizard(models.TransientModel):
    """Add a video / 3D animation / leaflet to the Patient Education Library.

    The media is stored as a regular DMS file in the branch's
    "Dental Hospital / Patient Education Library / <topic>" folder.
    """
    _name = 'dental.education.media.wizard'
    _description = 'Add Patient Education Media'

    topic_id = fields.Many2one('dms.category', string='Treatment Topic', required=True,
                               domain=[('dental_is_education_topic', '=', True)])
    name = fields.Char(string='Title', required=True)
    media_type = fields.Selection(MEDIA_TYPES, string='Media Type', required=True, default='video')
    purpose = fields.Selection(PURPOSES, string='Purpose', required=True, default='pre_treatment')
    lang_id = fields.Many2one('res.lang', string='Language', required=True,
                              default=lambda self: self.env['res.lang']._lang_get(self.env.user.lang))
    master_id = fields.Many2one(
        'dms.file', string='Language Version Of',
        domain="[('dental_doc_type', '=', 'education'), ('dental_edu_master_id', '=', False)]",
        help='Select the original video when uploading a translated / dubbed version.')
    product_ids = fields.Many2many('product.template', string='Also Recommend For',
                                   domain=[('is_dental_treatment', '=', True)])
    file = fields.Binary(string='Media File', required=True, attachment=False)
    file_name = fields.Char()
    thumbnail = fields.Image(string='Thumbnail', max_width=1024, max_height=1024)
    duration = fields.Char(string='Duration', help='e.g. 03:20')
    description = fields.Text(string='Patient-facing Description')

    @api.onchange('master_id')
    def _onchange_master_id(self):
        if self.master_id:
            self.topic_id = self.master_id.category_id
            self.media_type = self.master_id.dental_edu_media_type
            self.purpose = self.master_id.dental_edu_purpose
            if not self.name:
                self.name = self.master_id.name.rsplit('.', 1)[0]

    def action_add(self):
        self.ensure_one()
        if not any(self.env.user.has_group(g) for g in EDU_MANAGER_GROUPS):
            raise AccessError(_('Only clinic managers can add media to the Patient Education Library.'))
        if not self.file:
            raise UserError(_('Please select a file.'))
        company = self.env.company
        folder = self.env['dental.dms.service'].sudo()._get_education_folder(company, self.topic_id)
        extension = self.file_name.rsplit('.', 1)[1] if self.file_name and '.' in self.file_name else ''
        title = clean_name(self.name, default=_('Media'))
        if self.lang_id and self.master_id:
            title = f'{title} ({self.lang_id.code})'
        name = f'{title}.{extension}' if extension and not title.lower().endswith(f'.{extension.lower()}') else title
        names = folder.file_ids.mapped('name')
        if name in names:
            name = dms_file_tools.unique_name(name, names, bool(extension))
        vals = {
            'name': name,
            'directory_id': folder.id,
            'content': self.file,
            'category_id': self.topic_id.id,
            'dental_doc_type': 'education',
            'dental_edu_media_type': self.media_type,
            'dental_edu_purpose': self.purpose,
            'dental_edu_lang_id': self.lang_id.id,
            'dental_edu_master_id': self.master_id.id,
            'dental_edu_product_ids': [(6, 0, self.product_ids.ids)],
            'dental_edu_duration': self.duration,
            'dental_edu_description': self.description,
            'document_owner_id': self.env.user.id,
        }
        # sudo: DMS Enterprise restricts file creation to DMS managers; the clinic-manager check is above.
        media = self.env['dms.file'].sudo().create(vals)
        if self.thumbnail:
            media.write({'image_1920': self.thumbnail})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'dms.file',
            'res_id': media.id,
            'view_mode': 'form',
            'views': [(self.env.ref('dental_dms_education.view_dms_file_form_education').id, 'form')],
            'target': 'current',
        }
