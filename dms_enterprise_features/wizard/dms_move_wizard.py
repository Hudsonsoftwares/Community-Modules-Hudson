# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html_escape

class DmsMoveWizard(models.TransientModel):
    _name = "dms.move.wizard"
    _description = "Move Files and Folders Wizard"

    res_model = fields.Selection(
        selection=[
            ("dms.file", "File"),
            ("dms.directory", "Folder"),
        ],
        string="Resource Model",
        required=True,
        default="dms.file",
    )
    file_ids = fields.Many2many(
        comodel_name="dms.file",
        string="Files to Move",
    )
    directory_ids = fields.Many2many(
        comodel_name="dms.directory",
        string="Folders to Move",
    )
    item_count = fields.Integer(
        string="Item Count",
        compute="_compute_item_info",
    )
    item_names = fields.Char(
        string="Items",
        compute="_compute_item_info",
    )
    current_directory_id = fields.Many2one(
        comodel_name="dms.directory",
        string="Current Folder",
        readonly=True,
    )
    destination_directory_id = fields.Many2one(
        comodel_name="dms.directory",
        string="Destination Folder",
        required=True,
        domain="[('is_trashed', '=', False)]",
    )
    has_explicit_rules = fields.Boolean(
        string="Has Explicit Rules",
        compute="_compute_permission_preview",
    )
    permission_preview_html = fields.Html(
        string="Permission Preview",
        compute="_compute_permission_preview",
        sanitize=False,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_model = self.env.context.get("active_model", "dms.file")
        active_ids = self.env.context.get("active_ids", [])
        
        if active_model == "dms.file":
            res["res_model"] = "dms.file"
            files = self.env["dms.file"].browse(active_ids)
            res["file_ids"] = [(6, 0, files.ids)]
            if files and files[0].directory_id:
                res["current_directory_id"] = files[0].directory_id.id
        elif active_model == "dms.directory":
            res["res_model"] = "dms.directory"
            dirs = self.env["dms.directory"].browse(active_ids)
            res["directory_ids"] = [(6, 0, dirs.ids)]
            if dirs and dirs[0].parent_id:
                res["current_directory_id"] = dirs[0].parent_id.id
        return res

    @api.depends("res_model", "file_ids", "directory_ids")
    def _compute_item_info(self):
        for wizard in self:
            if wizard.res_model == "dms.file":
                count = len(wizard.file_ids)
                wizard.item_count = count
                if count == 1:
                    wizard.item_names = wizard.file_ids[0].name or _("Untitled File")
                elif count > 1:
                    wizard.item_names = _("%s files: %s") % (count, ", ".join(wizard.file_ids.mapped("name")[:3]) + ("..." if count > 3 else ""))
                else:
                    wizard.item_names = _("No files selected")
            else:
                count = len(wizard.directory_ids)
                wizard.item_count = count
                if count == 1:
                    wizard.item_names = wizard.directory_ids[0].name or _("Untitled Folder")
                elif count > 1:
                    wizard.item_names = _("%s folders: %s") % (count, ", ".join(wizard.directory_ids.mapped("name")[:3]) + ("..." if count > 3 else ""))
                else:
                    wizard.item_names = _("No folders selected")

    def _get_effective_dir_permissions(self, directory, user):
        """Compute effective permissions granted by a directory to a given user."""
        if not directory:
            return {k: False for k in ['view', 'download', 'upload', 'edit', 'move', 'rename', 'delete', 'share']}
        if user.has_group('dms.group_dms_manager') or user.has_group('base.group_system'):
            return {k: True for k in ['view', 'download', 'upload', 'edit', 'move', 'rename', 'delete', 'share']}

        dir_perms = {
            'view': False, 'download': False, 'upload': False,
            'edit': False, 'move': False, 'rename': False,
            'delete': False, 'share': False,
        }
        partner_id = user.partner_id.id if user.partner_id else 0
        for perm in directory.complete_permission_line_ids:
            applies = False
            if perm.group_id and user in perm.group_id.users:
                applies = True
            elif perm.user_id and perm.user_id.id == user.id:
                applies = True
            elif perm.partner_id and perm.partner_id.id == partner_id:
                applies = True

            if applies:
                if perm.perm_view:     dir_perms['view'] = True
                if perm.perm_download: dir_perms['download'] = True
                if perm.perm_upload:   dir_perms['upload'] = True
                if perm.perm_edit:     dir_perms['edit'] = True
                if perm.perm_move:     dir_perms['move'] = True
                if perm.perm_rename:   dir_perms['rename'] = True
                if perm.perm_delete:   dir_perms['delete'] = True
                if perm.perm_share:    dir_perms['share'] = True
        return dir_perms

    def _get_effective_file_permissions(self, file_rec, target_dir, user):
        """Compute effective permissions for a file in target_dir for user."""
        dir_perms = self._get_effective_dir_permissions(target_dir, user)
        if user.has_group('dms.group_dms_manager') or user.has_group('base.group_system'):
            return dir_perms, False

        has_explicit = bool(file_rec.access_ids)
        if not has_explicit:
            return dir_perms, False

        # Apply file explicit access as ceiling restriction
        user_dept_ids = []
        if hasattr(user, "employee_ids"):
            user_dept_ids = user.employee_ids.mapped("department_id").ids

        file_perms = {
            'view': False, 'download': False,
            'edit': False, 'move': False, 'rename': False,
            'delete': False, 'share': False,
        }
        user_matched = False
        for access in file_rec.access_ids:
            applies = False
            if access.user_id and access.user_id.id == user.id:
                applies = True
            elif access.group_id and user in access.group_id.user_ids:
                applies = True
            elif access.department_id and access.department_id.id in user_dept_ids:
                applies = True

            if applies:
                user_matched = True
                if access.perm_view:     file_perms['view'] = True
                if access.perm_download: file_perms['download'] = True
                if access.perm_edit:     file_perms['edit'] = True
                if access.perm_move:     file_perms['move'] = True
                if access.perm_rename:   file_perms['rename'] = True
                if access.perm_delete:   file_perms['delete'] = True
                if access.perm_share:    file_perms['share'] = True

        effective = {}
        if user_matched:
            effective['view'] = dir_perms['view'] and file_perms['view']
            effective['download'] = dir_perms['download'] and file_perms['download']
            effective['upload'] = dir_perms['upload']
            effective['edit'] = dir_perms['edit'] and file_perms['edit']
            effective['move'] = dir_perms['move'] and file_perms['move']
            effective['rename'] = dir_perms['rename'] and file_perms['rename']
            effective['delete'] = dir_perms['delete'] and file_perms['delete']
            effective['share'] = dir_perms['share'] and file_perms['share']
        else:
            effective = {k: False for k in ['view', 'download', 'upload', 'edit', 'move', 'rename', 'delete', 'share']}
        return effective, True

    @api.depends("res_model", "file_ids", "directory_ids", "current_directory_id", "destination_directory_id")
    def _compute_permission_preview(self):
        for wizard in self:
            if not wizard.destination_directory_id:
                wizard.permission_preview_html = """
                    <div class="alert alert-info d-flex align-items-center mb-0" role="alert">
                        <i class="fa fa-info-circle fa-2x me-3 text-info"></i>
                        <div>
                            Please select a destination folder to proceed with the move.
                        </div>
                    </div>
                """
                wizard.has_explicit_rules = False
                continue

            dest_name = html_escape(wizard.destination_directory_id.name or _("Selected Folder"))
            curr_name = html_escape(wizard.current_directory_id.name) if wizard.current_directory_id else _("Root")
            item_type = _("file(s)") if wizard.res_model == "dms.file" else _("folder(s)")

            has_explicit = False
            if wizard.res_model == "dms.file" and wizard.file_ids:
                has_explicit = any(bool(f.access_ids) for f in wizard.file_ids)
            wizard.has_explicit_rules = has_explicit

            explicit_text = ""
            if has_explicit:
                explicit_text = _("<br/><span class='text-muted small'><i class='fa fa-shield me-1'></i>Note: Explicit custom file access rules will continue to apply within the destination folder's permissions.</span>")

            html = f"""
            <div class="alert alert-warning d-flex align-items-start mb-0 shadow-sm border-warning" role="alert">
                <i class="fa fa-exclamation-triangle fa-2x me-3 text-warning flex-shrink-0 mt-1"></i>
                <div>
                    <strong class="d-block mb-1">{_('Access Rights Notice')}</strong>
                    <div class="text-dark">
                        {_('Moving these %s from <strong>%s</strong> into <strong>%s</strong> will update access rights for users and user groups according to the destination folder permissions.') % (item_type, curr_name, dest_name)}
                        {explicit_text}
                    </div>
                </div>
            </div>
            """
            wizard.permission_preview_html = html


    def action_move(self):
        self.ensure_one()
        dest_dir = self.destination_directory_id
        if not dest_dir:
            raise UserError(_("Please select a destination folder."))

        if dest_dir.is_trashed:
            raise UserError(_("Cannot move into a trashed folder."))

        # Permission check on destination directory
        user = self.env.user
        is_manager = user.has_group('dms.group_dms_manager') or user.has_group('base.group_system')
        if not is_manager:
            dest_perms = self._get_effective_dir_permissions(dest_dir, user)
            if not dest_perms.get('upload') and not dest_perms.get('edit'):
                raise UserError(_("You do not have permission to upload or create items in '%s'.") % dest_dir.name)

        if self.res_model == "dms.file":
            if not self.file_ids:
                raise UserError(_("No files selected to move."))

            for file_rec in self.file_ids:
                if file_rec.is_locked:
                    raise UserError(_("Cannot move file '%s' because it is locked by %s. Please unlock it first.") % (file_rec.name, file_rec.locked_by.name or 'another user'))
                if not is_manager and not file_rec.permission_move:
                    raise UserError(_("You do not have permission to move file '%s'.") % file_rec.name)
                if file_rec.directory_id == dest_dir:
                    continue  # Already in this folder
                file_rec.write({"directory_id": dest_dir.id})
                self.env['dms.file.log'].sudo().create({
                    'name': file_rec.name,
                    'file_id': file_rec.id,
                    'action': 'edit',
                    'details': f"Moved to folder '{dest_dir.name}'"
                })

            message = _("%s file(s) moved successfully to '%s'.") % (len(self.file_ids), dest_dir.name)

        elif self.res_model == "dms.directory":
            if not self.directory_ids:
                raise UserError(_("No folders selected to move."))

            for dir_rec in self.directory_ids:
                if not is_manager and not dir_rec.permission_move:
                    raise UserError(_("You do not have permission to move folder '%s'.") % dir_rec.name)

                # Cycle Prevention
                if dir_rec.id == dest_dir.id:
                    raise ValidationError(_("Cannot move folder '%s' inside itself.") % dir_rec.name)

                # Check if dest_dir is a descendant of dir_rec
                parent_check = dest_dir
                while parent_check:
                    if parent_check.id == dir_rec.id:
                        raise ValidationError(_("Cannot move folder '%s' inside its own subfolder '%s'.") % (dir_rec.name, dest_dir.name))
                    parent_check = parent_check.parent_id

                if dir_rec.parent_id == dest_dir:
                    continue  # Already in this folder

                dir_rec.write({"parent_id": dest_dir.id})

            message = _("%s folder(s) moved successfully to '%s'.") % (len(self.directory_ids), dest_dir.name)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Moved Successfully"),
                "message": message,
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.client",
                    "tag": "reload",
                }
            }
        }
