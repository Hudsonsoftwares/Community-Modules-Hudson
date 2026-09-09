# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

class HrEmployee(models.Model):
    _inherit = "hr.employee"

    dms_directory_id = fields.Many2one(
        "dms.directory",
        string="DMS Folder",
        readonly=True,
        ondelete="set null",
        copy=False,
    )
    dms_access_group_id = fields.Many2one(
        "dms.access.group",
        string="DMS Access Group",
        readonly=True,
        ondelete="set null",
        copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        for employee in employees:
            employee._setup_dms_folder_and_permissions()
        return employees

    def write(self, vals):
        res = super().write(vals)
        for employee in self:
            if "name" in vals:
                # Rename directory and access group
                if employee.dms_directory_id:
                    employee.dms_directory_id.sudo().name = employee.name
                if employee.dms_access_group_id:
                    employee.dms_access_group_id.sudo().name = f"Access Group - {employee.name}"
            
            if "user_id" in vals:
                # Sync user_id to the access group
                if employee.dms_access_group_id:
                    if employee.user_id:
                        employee.dms_access_group_id.sudo().write({
                            "explicit_user_ids": [(6, 0, [employee.user_id.id])]
                        })
                    else:
                        employee.dms_access_group_id.sudo().write({
                            "explicit_user_ids": [(6, 0, [])]
                        })
                else:
                    employee._setup_dms_folder_and_permissions()
        return res

    def _get_company_root_directory(self, company):
        """Find or create the 'Employee - {Company}' root directory."""
        dir_name = f"Employee - {company.name}"
        root_dir = self.env["dms.directory"].sudo().search([
            ("name", "=", dir_name),
            ("is_root_directory", "=", True),
        ], limit=1)

        if not root_dir:
            # Look for the default 'Employees' folder
            default_hr = self.env.ref("dms_enterprise_features.dms_dir_employees", raise_if_not_found=False)
            if default_hr and default_hr.name == "Employees":
                # Rename the existing default folder for the first company
                default_hr.sudo().write({"name": dir_name})
                root_dir = default_hr
            else:
                storage_id = default_hr.storage_id.id if default_hr else False
                root_dir = self.env["dms.directory"].sudo().create({
                    "name": dir_name,
                    "is_root_directory": True,
                    "storage_id": storage_id,
                })
                
                # Optionally give enterprise full access to it
                enterprise_group = self.env.ref("dms_enterprise_features.dms_access_group_enterprise", raise_if_not_found=False)
                if enterprise_group:
                    root_dir.sudo().write({"group_ids": [(4, enterprise_group.id)]})
                
        return root_dir

    def _setup_dms_folder_and_permissions(self):
        """Creates the DMS folder and assigns View & Download permissions."""
        self.ensure_one()
        if self.dms_directory_id:
            return  # Already set up

        # 1. Get Root Directory
        root_dir = self._get_company_root_directory(self.company_id or self.env.company)

        # 2. Create Employee Subfolder
        employee_dir = self.env["dms.directory"].sudo().create({
            "name": self.name,
            "parent_id": root_dir.id,
            "storage_id": root_dir.storage_id.id,
        })

        # 3. Create Access Group
        users = [(4, self.user_id.id)] if self.user_id else []
        access_group = self.env["dms.access.group"].sudo().create({
            "name": f"Access Group - {self.name}",
            "explicit_user_ids": users,
        })

        # 4. Link Access Group to Directory with View/Download permissions
        self.env["dms.directory.permission"].sudo().create({
            "directory_id": employee_dir.id,
            "group_id": access_group.id,
            "perm_view": True,
            "perm_download": True,
            "perm_upload": False,
            "perm_edit": False,
            "perm_rename": False,
            "perm_move": False,
            "perm_delete": False,
            "perm_share": False,
        })

        # 5. Link to Employee
        self.sudo().write({
            "dms_directory_id": employee_dir.id,
            "dms_access_group_id": access_group.id,
        })

    def action_setup_dms_folders(self):
        """Server action for existing employees."""
        for employee in self:
            employee._setup_dms_folder_and_permissions()
