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
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Contact",
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

    @api.model
    def _ensure_user_for_partner(self, partner):
        """Find an existing active user for the partner or create a portal user."""
        if not partner:
            return False
        
        # 1. Existing user
        user = partner.user_ids.filtered(lambda u: u.active)[:1] or partner.user_ids[:1]
        if not user:
            user = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)], limit=1)
            
        if user:
            # Ensure proper group: if internal user, ensure DMS user group; if not internal, ensure portal group
            if user.has_group('base.group_user'):
                dms_user_group = self.env.ref('dms.group_dms_user', raise_if_not_found=False)
                if dms_user_group and not user.has_group('dms.group_dms_user'):
                    dms_user_group.sudo().write({'user_ids': [(4, user.id)]})
            elif not user.has_group('base.group_portal'):
                portal_group = self.env.ref('base.group_portal', raise_if_not_found=False)
                if portal_group:
                    portal_group.sudo().write({'user_ids': [(4, user.id)]})
            return user

        # 2. No user exists for this contact -> create a portal user
        portal_group = self.env.ref('base.group_portal', raise_if_not_found=False)
        login = (partner.email or '').strip()
        if not login or self.env['res.users'].sudo().search_count([('login', '=', login)]):
            login = f"portal_user_{partner.id}"
            
        try:
            user_vals = {
                'name': partner.name,
                'login': login,
                'partner_id': partner.id,
                'email': partner.email or False,
                'active': True,
            }
            if portal_group:
                user_vals['group_ids'] = [(4, portal_group.id)]
                
            user = self.env['res.users'].sudo().with_context(no_reset_password=True).create(user_vals)
            return user
        except Exception:
            user = self.env['res.users'].sudo().search([('partner_id', '=', partner.id)], limit=1)
            return user or False

    @api.onchange('perm_download', 'perm_edit', 'perm_rename', 'perm_move', 'perm_delete', 'perm_share')
    def _onchange_sub_permissions(self):
        if any([self.perm_download, self.perm_edit, self.perm_rename, self.perm_move, self.perm_delete, self.perm_share]):
            self.perm_view = True
        if self.perm_edit:
            self.perm_download = True

    @api.onchange('perm_view')
    def _onchange_perm_view(self):
        if not self.perm_view:
            self.perm_download = False
            self.perm_edit = False
            self.perm_rename = False
            self.perm_move = False
            self.perm_delete = False
            self.perm_share = False

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id:
            user = self._ensure_user_for_partner(self.partner_id)
            if user:
                self.user_id = user.id

    @api.onchange('user_id')
    def _onchange_user_id(self):
        if self.user_id and not self.partner_id:
            self.partner_id = self.user_id.partner_id.id

    @api.constrains('partner_id', 'user_id', 'group_id', 'department_id')
    def _check_target(self):
        for record in self:
            targets = [bool(record.partner_id or record.user_id), bool(record.group_id), bool(record.department_id)]
            if sum(targets) != 1:
                raise ValidationError(_("You must select exactly one target (Contact/User, User Group, or Department) for this access rule."))

    def _normalize_permissions(self, vals):
        sub_perms = ['perm_download', 'perm_edit', 'perm_rename', 'perm_move', 'perm_delete', 'perm_share']
        if any(vals.get(p) for p in sub_perms):
            vals['perm_view'] = True
        if vals.get('perm_edit'):
            vals['perm_download'] = True
        if 'perm_view' in vals and not vals['perm_view']:
            for p in sub_perms:
                vals[p] = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._normalize_permissions(vals)
            if vals.get('partner_id') and not vals.get('user_id'):
                partner = self.env['res.partner'].browse(vals['partner_id'])
                user = self._ensure_user_for_partner(partner)
                if user:
                    vals['user_id'] = user.id
            elif vals.get('user_id') and not vals.get('partner_id'):
                user = self.env['res.users'].browse(vals['user_id'])
                if user.partner_id:
                    vals['partner_id'] = user.partner_id.id

        records = super().create(vals_list)
        # Ensure targeted internal users have DMS user group to see the app
        dms_user_group = self.env.ref('dms.group_dms_user', raise_if_not_found=False)
        portal_group = self.env.ref('base.group_portal', raise_if_not_found=False)
        for record in records:
            if record.user_id:
                if record.user_id.has_group('base.group_user') and dms_user_group and not record.user_id.has_group('dms.group_dms_user'):
                    dms_user_group.sudo().write({'user_ids': [(4, record.user_id.id)]})
                elif not record.user_id.has_group('base.group_user') and portal_group and not record.user_id.has_group('base.group_portal'):
                    portal_group.sudo().write({'user_ids': [(4, record.user_id.id)]})
        return records

    def write(self, vals):
        self._normalize_permissions(vals)
        if vals.get('partner_id') and 'user_id' not in vals:
            partner = self.env['res.partner'].browse(vals['partner_id'])
            user = self._ensure_user_for_partner(partner)
            vals['user_id'] = user.id if user else False
        elif vals.get('user_id') and 'partner_id' not in vals:
            user = self.env['res.users'].browse(vals['user_id'])
            if user.partner_id:
                vals['partner_id'] = user.partner_id.id

        res = super().write(vals)
        if 'user_id' in vals or 'partner_id' in vals:
            dms_user_group = self.env.ref('dms.group_dms_user', raise_if_not_found=False)
            portal_group = self.env.ref('base.group_portal', raise_if_not_found=False)
            for record in self:
                if record.user_id:
                    if record.user_id.has_group('base.group_user') and dms_user_group and not record.user_id.has_group('dms.group_dms_user'):
                        dms_user_group.sudo().write({'user_ids': [(4, record.user_id.id)]})
                    elif not record.user_id.has_group('base.group_user') and portal_group and not record.user_id.has_group('base.group_portal'):
                        portal_group.sudo().write({'user_ids': [(4, record.user_id.id)]})
        return res
