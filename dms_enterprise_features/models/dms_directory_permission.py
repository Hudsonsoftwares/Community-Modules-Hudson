from odoo import models, fields

class DmsDirectoryPermission(models.Model):
    _name = "dms.directory.permission"
    _description = "Directory Permission"

    directory_id = fields.Many2one(
        "dms.directory",
        string="Directory",
        required=True,
        ondelete="cascade",
    )
    group_id = fields.Many2one(
        "dms.access.group",
        string="Access Group",
        required=True,
        ondelete="cascade",
    )
    
    perm_view = fields.Boolean("View", default=False)
    perm_download = fields.Boolean("Download", default=False)
    perm_upload = fields.Boolean("Upload", default=False)
    perm_edit = fields.Boolean("Edit", default=False)
    perm_rename = fields.Boolean("Rename", default=False)
    perm_move = fields.Boolean("Move", default=False)
    perm_delete = fields.Boolean("Delete", default=False)
    perm_share = fields.Boolean("Share", default=False)

    _sql_constraints = [
        (
            "directory_group_unique",
            "unique(directory_id, group_id)",
            "An access group can only have one permission rule per directory.",
        )
    ]
