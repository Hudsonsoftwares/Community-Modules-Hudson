# -*- coding: utf-8 -*-
import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models.const import DOC_TYPES


class DentalDmsUploadWizard(models.TransientModel):
    """Upload a document from any dental screen.

    The file becomes an ordinary attachment of the dental record (created with the user's own
    rights) and is then filed in the DMS by the standard routing - no separate storage.
    """
    _name = 'dental.dms.upload.wizard'
    _description = 'Add Dental Document'

    res_model = fields.Char(required=True, readonly=True)
    res_id = fields.Integer(required=True, readonly=True)
    record_name = fields.Char(string='Linked To', compute='_compute_record_name')
    doc_type = fields.Selection(DOC_TYPES, string='Document Type', required=True, default='patient')
    file = fields.Binary(string='File', required=True, attachment=False)
    file_name = fields.Char(string='File Name')
    name = fields.Char(string='Title', help='Leave empty to keep the file name.')
    document_date = fields.Date(string='Document Date', default=fields.Date.context_today)
    tooth_reference = fields.Char(string='Tooth / Teeth', help='FDI tooth number(s), e.g. 36 or 11,21')
    notes = fields.Text(string='Clinical Notes')

    @api.depends('res_model', 'res_id')
    def _compute_record_name(self):
        for wizard in self:
            record = wizard._get_record()
            wizard.record_name = record.display_name if record else False

    def _get_record(self):
        self.ensure_one()
        if not self.res_model or self.res_model not in self.env or not self.res_id:
            return False
        return self.env[self.res_model].browse(self.res_id).exists()

    def _raw_content(self):
        value = self.file
        if hasattr(value, 'content'):
            return value.content
        if isinstance(value, (bytes, bytearray)):
            try:
                return base64.b64decode(value, validate=True)
            except ValueError:
                return bytes(value)
        return base64.b64decode(value or b'')

    def action_upload(self):
        self.ensure_one()
        record = self._get_record()
        service = self.env['dental.dms.service']
        if not record or not service._is_dental_source(record._name):
            raise UserError(_('The document cannot be linked to this record.'))
        # The user must be allowed to work on the record the document belongs to.
        record.check_access('write')
        raw = self._raw_content()
        if not raw:
            raise UserError(_('Please select a file.'))
        file_name = self.file_name or _('Document')
        name = file_name
        if self.name:
            extension = file_name.rsplit('.', 1)[1] if '.' in file_name else ''
            name = f'{self.name}.{extension}' if extension and not self.name.lower().endswith(f'.{extension.lower()}') \
                else self.name
        extra = {
            'dental_document_date': self.document_date,
            'dental_tooth_reference': self.tooth_reference,
            'dental_notes': self.notes,
        }
        dms_file = service._store_document(record, name, raw, doc_type=self.doc_type, extra=extra)
        if not dms_file:
            raise UserError(_('The document was attached to the record but could not be filed in the '
                              'Document Management System. Please check the server log.'))
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'success', 'title': _('Document added'),
                       'message': _('"%s" was filed in %s.', dms_file.sudo().name,
                                    dms_file.sudo().directory_id.complete_name),
                       'next': {'type': 'ir.actions.act_window_close'}},
        }
