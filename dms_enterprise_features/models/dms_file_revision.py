# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

class DMSFileRevision(models.Model):
    _name = "dms.file.revision"
    _description = "Document Revision"
    _order = "create_date desc, version desc"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    file_id = fields.Many2one(
        comodel_name="dms.file",
        string="Document",
        required=True,
        ondelete="cascade",
        index=True
    )
    version = fields.Char(
        string="Version",
        required=True,
        tracking=True
    )
    content = fields.Binary(
        string="File Content",
        required=True,
        attachment=True
    )
    file_name = fields.Char(string="File Name")
    uploader_id = fields.Many2one(
        comodel_name="res.users",
        string="Uploaded By",
        default=lambda self: self.env.user,
        readonly=True
    )
    upload_date = fields.Datetime(
        string="Upload Date",
        default=fields.Datetime.now,
        readonly=True
    )
    comments = fields.Text(string="Comments")
    approval_history_ids = fields.One2many(
        comodel_name="dms.file.approval",
        inverse_name="revision_id",
        string="Approval History"
    )
    signature_request_ids = fields.One2many(
        comodel_name="dms.file.signature.request",
        inverse_name="revision_id",
        string="Signature Requests"
    )

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, f"{record.file_id.name} - v{record.version}"))
        return result

    def action_make_current(self):
        self.ensure_one()
        self.file_id.write({
            'current_revision_id': self.id,
            'content': self.content
        })
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if not record.file_id.current_revision_id:
                record.action_make_current()
        return records
