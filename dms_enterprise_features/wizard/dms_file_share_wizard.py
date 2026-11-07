# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import html_escape

class DmsFileShareWizard(models.TransientModel):
    _name = "dms.file.share.wizard"
    _description = "Share Document Wizard"

    file_id = fields.Many2one(
        comodel_name="dms.file",
        string="Document",
        required=True,
    )
    file_name = fields.Char(
        string="Document Name",
        related="file_id.name",
        readonly=True,
    )
    share_mode = fields.Selection(
        selection=[
            ("people", "Add People"),
            ("groups", "Add Groups"),
        ],
        string="Share Mode",
        default="people",
        required=True,
    )
    partner_ids = fields.Many2many(
        comodel_name="res.partner",
        string="Add people, contacts, or email addresses",
    )
    group_ids = fields.Many2many(
        comodel_name="res.groups",
        string="Add groups",
    )
    new_access_role = fields.Selection(
        selection=[
            ("viewer", "Viewer"),
            ("editor", "Editor"),
        ],
        string="Role",
        default="viewer",
        required=True,
    )
    share_internal_access = fields.Selection(
        selection=[
            ("none", "No access"),
            ("viewer", "Viewer"),
            ("editor", "Editor"),
        ],
        string="Internal Users",
        default="editor",
        required=True,
    )
    share_link_access = fields.Selection(
        selection=[
            ("none", "No access"),
            ("viewer", "Viewer"),
            ("editor", "Editor"),
        ],
        string="Access Through Link",
        default="none",
        required=True,
    )
    share_is_discoverable = fields.Selection(
        selection=[
            ("no", "No"),
            ("yes", "Yes"),
        ],
        string="Discoverable",
        default="no",
        required=True,
    )
    share_link_url = fields.Char(
        string="Share Link",
        compute="_compute_share_link_url",
    )
    people_with_access_html = fields.Html(
        string="People with Access",
        compute="_compute_people_with_access_html",
        sanitize=False,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get("active_id") or self.env.context.get("default_file_id")
        if active_id:
            file_rec = self.env["dms.file"].browse(active_id)
            if file_rec.exists():
                if file_rec.is_locked and not file_rec.is_lock_editor and not self.env.user.has_group('dms.group_dms_manager') and not self.env.su:
                    raise UserError(_("Cannot share '%s' because it is locked by %s.") % (file_rec.name, file_rec.locked_by.name or 'another user'))
                if not file_rec.permission_share and not self.env.user.has_group('dms.group_dms_manager') and not self.env.su:
                    raise UserError(_("You do not have permission to share '%s'.") % file_rec.name)
                res["file_id"] = file_rec.id
                res["share_internal_access"] = file_rec.share_internal_access or "editor"
                res["share_link_access"] = file_rec.share_link_access or "none"
                res["share_is_discoverable"] = file_rec.share_is_discoverable or "no"
        return res

    @api.depends("file_id")
    def _compute_share_link_url(self):
        for wizard in self:
            if wizard.file_id:
                wizard.share_link_url = wizard.file_id.share_link_url
            else:
                wizard.share_link_url = False

    @api.depends("file_id", "file_id.access_ids", "file_id.document_owner_id")
    def _compute_people_with_access_html(self):
        def avatar(url):
            return f'<img class="o_dms_share_avatar" src="{url}" alt=""/>'

        def icon(paths):
            return (
                '<span class="o_dms_share_avatar o_dms_share_avatar_icon">'
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18" '
                'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                f'stroke-linejoin="round" aria-hidden="true">{paths}</svg></span>'
            )

        group_icon = icon(
            '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/>'
            '<path d="M16 4.5a3.5 3.5 0 0 1 0 7"/><path d="M18.5 20a6.5 6.5 0 0 0-2.5-5.1"/>'
        )
        department_icon = icon(
            '<path d="M3 21h18"/><path d="M5 21V7l7-4 7 4v14"/><path d="M10 21v-4h4v4"/>'
        )

        def row(visual, name, sub, role, role_label, tag=""):
            return (
                '<div class="o_dms_share_row">'
                f'{visual}'
                '<div class="o_dms_share_row_text">'
                f'<div class="o_dms_share_row_title">{html_escape(name)}{tag}</div>'
                f'<div class="o_dms_share_row_sub">{html_escape(sub)}</div>'
                '</div>'
                f'<span class="o_dms_share_role o_dms_share_role_{role}">{html_escape(role_label)}</span>'
                '</div>'
            )

        for wizard in self:
            if not wizard.file_id:
                wizard.people_with_access_html = ""
                continue

            file_rec = wizard.file_id
            rows_html = []

            # 1. Document owner
            owner = file_rec.document_owner_id or file_rec.create_uid
            if owner:
                rows_html.append(row(
                    avatar(f"/web/image/res.users/{owner.id}/avatar_128"),
                    owner.name or "",
                    owner.email or "",
                    "editor",
                    _("Editor"),
                    tag=f'<span class="o_dms_share_tag">{html_escape(_("Owner"))}</span>',
                ))

            # 2. Explicit user / group access rules
            for access in file_rec.access_ids:
                is_editor = access.perm_edit or access.perm_rename or access.perm_move
                role = "editor" if is_editor else "viewer"
                role_label = _("Editor") if is_editor else _("Viewer")

                if access.partner_id:
                    visual = avatar(f"/web/image/res.partner/{access.partner_id.id}/avatar_128")
                    name, sub = access.partner_id.name or "", access.partner_id.email or ""
                elif access.user_id:
                    visual = avatar(f"/web/image/res.users/{access.user_id.id}/avatar_128")
                    name, sub = access.user_id.name or "", access.user_id.email or ""
                elif access.group_id:
                    visual, name, sub = group_icon, access.group_id.name or "", _("User group")
                elif access.access_group_id:
                    visual, name, sub = group_icon, access.access_group_id.name or "", _("Access group")
                elif access.department_id:
                    visual, name, sub = department_icon, access.department_id.name or "", _("Department")
                else:
                    continue
                rows_html.append(row(visual, name, sub, role, role_label))

            wizard.people_with_access_html = "".join(rows_html)

    @api.onchange("share_link_access", "share_internal_access", "share_is_discoverable")
    def _onchange_share_settings(self):
        for wizard in self:
            if wizard.file_id:
                wizard.file_id.sudo().write({
                    "share_internal_access": wizard.share_internal_access,
                    "share_link_access": wizard.share_link_access,
                    "share_is_discoverable": wizard.share_is_discoverable,
                })
                wizard.share_link_url = wizard.file_id.share_link_url

    def action_add_access(self):
        """Add selected contacts or groups to file access rules."""
        self.ensure_one()
        file_rec = self.file_id
        if not file_rec:
            return

        if file_rec.is_locked and not file_rec.is_lock_editor and not self.env.user.has_group('dms.group_dms_manager') and not self.env.su:
            raise UserError(_("Cannot modify access because '%s' is locked by %s.") % (file_rec.name, file_rec.locked_by.name or 'another user'))
        if not file_rec.permission_share and not self.env.user.has_group('dms.group_dms_manager') and not self.env.su:
            raise UserError(_("You do not have permission to share '%s'.") % file_rec.name)

        is_editor = (self.new_access_role == "editor")
        perm_vals = {
            "perm_view": True,
            "perm_download": True,
            "perm_edit": is_editor,
            "perm_rename": is_editor,
            "perm_move": is_editor,
            "perm_delete": is_editor,
            "perm_share": is_editor,
        }

        if self.share_mode == "people" and self.partner_ids:
            for partner in self.partner_ids:
                user = self.env['dms.file.access']._ensure_user_for_partner(partner)
                existing = file_rec.access_ids.filtered(lambda a: (a.partner_id.id == partner.id) or (user and a.user_id.id == user.id))
                if existing:
                    existing.write({
                        **perm_vals,
                        "partner_id": partner.id,
                        "user_id": user.id if user else False,
                    })
                else:
                    self.env["dms.file.access"].create({
                        "file_id": file_rec.id,
                        "partner_id": partner.id,
                        "user_id": user.id if user else False,
                        **perm_vals,
                    })
            self.partner_ids = [(5, 0, 0)]

        elif self.share_mode == "groups" and self.group_ids:
            for group in self.group_ids:
                existing = file_rec.access_ids.filtered(lambda a: a.group_id.id == group.id)
                if existing:
                    existing.write(perm_vals)
                else:
                    self.env["dms.file.access"].create({
                        "file_id": file_rec.id,
                        "group_id": group.id,
                        **perm_vals,
                    })
            self.group_ids = [(5, 0, 0)]

        # Also persist general access settings
        file_rec.write({
            "share_internal_access": self.share_internal_access,
            "share_link_access": self.share_link_access,
            "share_is_discoverable": self.share_is_discoverable,
        })
        self.share_link_url = file_rec.share_link_url

        # Re-open wizard to show updated list
        return {
            "type": "ir.actions.act_window",
            "res_model": "dms.file.share.wizard",
            "res_id": self.id,
            "views": [[False, "form"]],
            "view_mode": "form",
            "target": "new",
            "context": {"dialog_size": "md"},
        }

    def action_save(self):
        """Save General Access and any pending contacts/groups immediately to the document."""
        self.ensure_one()
        file_rec = self.file_id
        if not file_rec:
            return {"type": "ir.actions.act_window_close"}

        if file_rec.is_locked and not file_rec.is_lock_editor and not self.env.user.has_group('dms.group_dms_manager') and not self.env.su:
            raise UserError(_("Cannot modify access settings because '%s' is locked by %s.") % (file_rec.name, file_rec.locked_by.name or 'another user'))
        if not file_rec.permission_share and not self.env.user.has_group('dms.group_dms_manager') and not self.env.su:
            raise UserError(_("You do not have permission to share '%s'.") % file_rec.name)

        # 1. Process any pending contacts or groups if selected
        if self.partner_ids or self.group_ids:
            self.action_add_access()

        # 2. Write general access settings to document
        file_rec.write({
            "share_internal_access": self.share_internal_access,
            "share_link_access": self.share_link_access,
            "share_is_discoverable": self.share_is_discoverable,
        })
        self.share_link_url = file_rec.share_link_url

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Saved"),
                "message": _("Access settings saved successfully."),
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.act_window",
                    "res_model": "dms.file.share.wizard",
                    "res_id": self.id,
                    "views": [[False, "form"]],
                    "view_mode": "form",
                    "target": "new",
                    "context": {"dialog_size": "md"},
                }
            }
        }

    def action_save_and_close(self):
        """Save General Access settings to document and close."""
        self.action_save()
        return {"type": "ir.actions.act_window_close"}
