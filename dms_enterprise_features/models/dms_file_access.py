# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

class DMSFileAccess(models.Model):
    _name = "dms.file.access"
    _description = "File Explicit Access"
    
    file_id = fields.Many2one(
        comodel_name="dms.file",
        string="Document",
        required=True,
        ondelete="cascade"
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="User",
        required=True
    )
    perm_read = fields.Boolean(string="Read Access")
    perm_write = fields.Boolean(string="Write/Edit Access")
    perm_unlink = fields.Boolean(string="Delete Access")

    _sql_constraints = [
        ('file_user_uniq', 'unique(file_id, user_id)', 'A user can only have one explicit access record per document.')
    ]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Ensure users have DMS user group to see the app
        dms_user_group = self.env.ref('dms.group_dms_user', raise_if_not_found=False)
        if dms_user_group:
            for record in records:
                if record.user_id:
                    dms_user_group.sudo().write({'user_ids': [(4, record.user_id.id)]})
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'user_id' in vals:
            dms_user_group = self.env.ref('dms.group_dms_user', raise_if_not_found=False)
            if dms_user_group:
                for record in self:
                    if record.user_id:
                        dms_user_group.sudo().write({'user_ids': [(4, record.user_id.id)]})
        return res
