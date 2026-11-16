# -*- coding: utf-8 -*-
from odoo import api, models


class IrAttachment(models.Model):
    """File attachments of dental records into the DMS.

    Runs *after* the DMS / DMS Enterprise hooks (super() first), so an attachment they already
    filed is only enriched with dental links. Their behaviour is not altered.
    """
    _inherit = 'ir.attachment'

    @api.model_create_multi
    def create(self, vals_list):
        attachments = super().create(vals_list)
        attachments._dental_dms_file()
        return attachments

    def write(self, vals):
        res = super().write(vals)
        if 'res_model' in vals or 'res_id' in vals:
            self._dental_dms_file()
        return res

    def _dental_dms_file(self):
        ctx = self.env.context
        if ctx.get('dms_file') or ctx.get('dental_dms_skip') or ctx.get('install_mode') and not ctx.get('dental_dms_force'):
            return
        service = self.env['dental.dms.service'].sudo()
        candidates = self.filtered(lambda a: a.res_id and service._is_dental_source(a.res_model))
        for attachment in candidates:
            service._route_attachment(attachment, doc_type=ctx.get('dental_dms_doc_type'),
                                      extra=ctx.get('dental_dms_extra'))
