from odoo import models, api, fields, _
from odoo.exceptions import AccessError, ValidationError

class DmsDirectory(models.Model):
    _inherit = 'dms.directory'

    @api.constrains("is_root_directory", "parent_id")
    def _check_directory_parent(self):
        """Override: if no parent and not flagged as root, we auto-promote to root
        in create(), so we skip the error here — it has already been handled."""
        for record in self:
            if record.is_root_directory and record.parent_id:
                raise ValidationError(
                    _("A directory can't be a root and have a parent directory.")
                )
            # The original raises an error when is_root_directory=False AND no parent.
            # We intentionally skip that case because create() pre-fills is_root_directory.

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Auto-promote to root directory when no parent is given
            if not vals.get('parent_id') and not vals.get('is_root_directory'):
                vals['is_root_directory'] = True
                if not vals.get('storage_id'):
                    # Use the default enterprise storage; fall back to any storage
                    storage = self.env.ref(
                        'dms_enterprise_features.dms_storage_enterprise', raise_if_not_found=False
                    ) or self.env['dms.storage'].search([], limit=1)
                    if storage:
                        vals['storage_id'] = storage.id
        return super().create(vals_list)


    @api.depends("count_files", "count_directories")
    def _compute_count_elements(self):
        """Override to neutralize element counting for performance."""
        for record in self:
            record.count_elements = 0

    @api.depends("child_directory_ids", "file_ids")
    def _compute_size(self):
        """Override to neutralize size computation for performance."""
        for record in self:
            record.size = 0
            record.human_size = ""

    @api.model
    def search_panel_select_range(self, field_name, **kwargs):
        res = super().search_panel_select_range(field_name, **kwargs)
        if isinstance(res, list):
            res = {"values": res}
        elif not isinstance(res, dict):
            res = {"values": []}
        elif "values" not in res:
            res["values"] = []
        return res

    @api.model
    def search_panel_select_multi_range(self, field_name, **kwargs):
        res = super().search_panel_select_multi_range(field_name, **kwargs)
        if isinstance(res, list):
            res = {"values": res}
        elif not isinstance(res, dict):
            res = {"values": []}
        elif "values" not in res:
            res["values"] = []
        return res

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        """Override to neutralize recursive full path computation."""
        for record in self:
            record.complete_name = record.name

    @api.onchange("tag_ids")
    def _onchange_tag_ids_autofill_category(self):
        for record in self:
            if not record.category_id and record.tag_ids:
                for tag in record.tag_ids:
                    if tag.category_id:
                        record.category_id = tag.category_id
                        break

    permission_line_ids = fields.One2many(
        "dms.directory.permission",
        "directory_id",
        string="Permission Lines",
    )
    group_permission_ids = fields.One2many(
        "dms.directory.permission",
        "directory_id",
        domain=[("group_id", "!=", False)],
        string="Access Group Permissions",
    )
    user_permission_ids = fields.One2many(
        "dms.directory.permission",
        "directory_id",
        domain=[("group_id", "=", False)],
        string="User Permissions",
    )

    complete_permission_line_ids = fields.Many2many(
        "dms.directory.permission",
        relation="dms_dir_complete_perm_rel",
        column1="dir_id",
        column2="perm_id",
        compute="_compute_complete_permission_line_ids",
        store=True,
        recursive=True,
    )

    @api.depends(
        "permission_line_ids",
        "parent_id.complete_permission_line_ids",
        "inherit_group_ids",
    )
    def _compute_complete_permission_line_ids(self):
        for one in self:
            perms = one.permission_line_ids
            if one.inherit_group_ids and one.parent_id:
                perms |= one.parent_id.complete_permission_line_ids
            one.complete_permission_line_ids = perms

    def write(self, vals):
        if not self.env.su and not self.env.user.has_group('dms.group_dms_manager'):
            for record in self:
                if 'name' in vals and not record.permission_rename:
                    raise AccessError(_("You do not have permission to rename this directory."))
                if 'parent_id' in vals and not record.permission_move:
                    raise AccessError(_("You do not have permission to move this directory."))
                # Edits to other fields might be considered "edit"
                edit_fields = set(vals.keys()) - {'name', 'parent_id'}
                if edit_fields and not record.permission_edit:
                    raise AccessError(_("You do not have permission to edit this directory."))
        return super().write(vals)

    # Trash Management
    is_trashed = fields.Boolean(
        string="In Trash",
        default=False,
    )
    trash_date = fields.Datetime(
        string="Trash Date"
    )
    parent_is_trashed = fields.Boolean(
        related='parent_id.is_trashed',
        string="Parent is Trashed"
    )

    def action_open_move_wizard(self):
        return {
            'name': _('Move Folder(s)'),
            'type': 'ir.actions.act_window',
            'res_model': 'dms.move.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'dms.directory',
                'active_ids': self.ids,
            },
        }

    def action_send_to_trash(self):
        for record in self:
            record.write({
                'is_trashed': True,
                'trash_date': fields.Datetime.now()
            })
            # Also trash all files within
            record.file_ids.action_send_to_trash()
            # And child directories
            record.child_directory_ids.action_send_to_trash()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_restore(self):
        for record in self:
            record.write({
                'is_trashed': False,
                'trash_date': False
            })
            # Restore files within
            record.file_ids.with_context(active_test=False).filtered('is_trashed').action_restore()
            # Restore child directories
            record.child_directory_ids.with_context(active_test=False).filtered('is_trashed').action_restore()
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def unlink(self):
        # Soft delete logic: if not in trash, send to trash instead.
        to_trash = self.filtered(lambda r: not r.is_trashed)
        if to_trash:
            to_trash.action_send_to_trash()
            
        to_delete = self - to_trash
        if to_delete:
            return super(DmsDirectory, to_delete).unlink()
        return True

    def action_open_form_view(self):
        self.ensure_one()
        if not self.permission_write and not self.env.user.has_group('dms.group_dms_manager') and not self.env.user.has_group('base.group_system'):
            raise UserError(_("You do not have permission to edit this directory."))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'dms.directory',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_download_directory_zip(self):
        self.ensure_one()
        if not self.permission_download and not self.env.user.has_group('dms.group_dms_manager') and not self.env.user.has_group('base.group_system'):
            raise UserError(_("You do not have permission to download files from this directory."))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/dms/directory/{self.id}/download_zip',
            'target': 'self',
        }
