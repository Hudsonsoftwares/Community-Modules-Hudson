# -*- coding: utf-8 -*-
import json

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.binary import BinaryBytes


class HudsonReportExportDMSWizard(models.TransientModel):
    _name = 'hudson.report.export.dms.wizard'
    _description = 'Export Report to Documents'

    export_format = fields.Selection([
        ('pdf', 'PDF'),
        ('xlsx', 'XLSX'),
    ], string="Export to", default='pdf', required=True)
    name = fields.Char(
        string="Documents Name", required=True,
        help="Name of the document created in Documents. The file extension is added automatically.")
    directory_id = fields.Many2one(
        'dms.directory', string="Folder", required=True,
        default=lambda self: self._default_directory_id(),
        domain="[('permission_create', '=', True)]",
        help="Folder of Documents the report is saved in.")
    tag_ids = fields.Many2many('dms.tag', string="Tags")
    # The report as displayed, sent by the report screen (see _getExportPayload in dynamic_report.js)
    report_data = fields.Text(string="Report Data JSON")

    @api.model
    def _default_directory_id(self):
        """The Finance folder, as in Odoo's Documents, or else the first folder the user can add to."""
        Directory = self.env['dms.directory']
        finance = self.env.ref('dms_enterprise_features.dms_dir_finance', raise_if_not_found=False)
        candidates = finance or Directory.search([('name', '=', 'Finance')], limit=1)
        candidates = candidates.filtered_domain([('permission_create', '=', True)]) if candidates else candidates
        return candidates[:1] or Directory.search([('permission_create', '=', True)], limit=1)

    def _get_report_payload(self):
        try:
            payload = json.loads(self.report_data or '{}')
        except ValueError:
            payload = {}
        if not payload.get('columns'):
            raise UserError(_("There is no report data to export. Reopen the report and try again."))
        return payload

    def action_export(self):
        self.ensure_one()
        payload = self._get_report_payload()
        snapshot = self.env['hudson.report.snapshot']
        extension = self.export_format
        title = (self.name or '').strip() or payload.get('title') or _("Report")
        if extension == 'xlsx':
            content = snapshot.render_xlsx(payload, name=title)
        else:
            content = snapshot.render_pdf(payload, name=title)

        # Documents refuses two files with the same name in a folder: number the copy
        base_name = title[:-len(extension) - 1] if title.lower().endswith('.' + extension) else title
        filename = snapshot._get_filename(base_name, extension)
        existing = set(self.directory_id.sudo().file_ids.mapped('name'))
        counter = 2
        while filename in existing:
            filename = snapshot._get_filename(f"{base_name} ({counter})", extension)
            counter += 1

        dms_file = self.env['dms.file'].create({
            'name': filename,
            'directory_id': self.directory_id.id,
            'tag_ids': [(6, 0, self.tag_ids.ids)],
            # Odoo 20 binary fields take a BinaryValue (raw bytes), not base64
            'content': BinaryBytes(content, filename=filename),
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Exported to Documents"),
                # "%s" is replaced client-side by the link below; "%" in the
                # folder name is escaped so it is not taken for a placeholder.
                'message': _("%(file)s was saved in %(folder)s.",
                             file='%s', folder=(self.directory_id.display_name or '').replace('%', '%%')),
                'links': [{'label': dms_file.name, 'url': f'/odoo/dms.file/{dms_file.id}'}],
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
