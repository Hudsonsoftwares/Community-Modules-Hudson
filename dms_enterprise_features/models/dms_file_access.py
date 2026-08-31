# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

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
    )
    group_id = fields.Many2one(
        comodel_name="res.groups",
        string="User Group",
    )
    department_id = fields.Many2one(
        comodel_name="hr.department",
        string="Department",
    )

    perm_view = fields.Boolean(string="View", default=False)
    perm_download = fields.Boolean(string="Download", default=False)
    perm_edit = fields.Boolean(string="Edit", default=False)
    perm_rename = fields.Boolean(string="Rename", default=False)
    perm_move = fields.Boolean(string="Move", default=False)
    perm_delete = fields.Boolean(string="Delete", default=False)
    perm_share = fields.Boolean(string="Share", default=False)

    @api.constrains('user_id', 'group_id', 'department_id')
    def _check_target(self):
        for record in self:
            targets = [bool(record.user_id), bool(record.group_id), bool(record.department_id)]
            if sum(targets) != 1:
                raise ValidationError(_("You must select exactly one target (User, User Group, or Department) for this access rule."))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Ensure targeted users have DMS user group to see the app
        dms_user_group = self.env.ref('dms.group_dms_user', raise_if_not_found=False)
        if dms_user_group:
            for record in records:
                if record.user_id:
                    dms_user_group.sudo().write({'user_ids': [(4, record.user_id.id)]})
                # Note: We don't auto-assign for group_id/department_id to avoid mass modification of users,
                # assuming the admin configured those groups correctly.
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
