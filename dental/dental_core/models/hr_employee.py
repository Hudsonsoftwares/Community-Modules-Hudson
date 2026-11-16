from odoo import api, models

# Employee fields that decide whether a user gets the Dentist Workspace
DENTIST_WORKSPACE_FIELDS = {'user_id', 'dental_role', 'active', 'company_id'}


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def _invalidate_dentist_workspace_menus(self):
        # Menus are cached per user (ir.ui.menu.load_menus / load_menus_root)
        self.env.transaction.invalidate_ormcache()

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        if any(vals.get('user_id') for vals in vals_list):
            self._invalidate_dentist_workspace_menus()
        return employees

    def write(self, vals):
        res = super().write(vals)
        if DENTIST_WORKSPACE_FIELDS.intersection(vals):
            self._invalidate_dentist_workspace_menus()
        return res

    def unlink(self):
        had_users = any(self.mapped('user_id'))
        res = super().unlink()
        if had_users:
            self._invalidate_dentist_workspace_menus()
        return res
