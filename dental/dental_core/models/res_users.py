from odoo import models

# Permission groups that may hold the Dentist Workspace (Clinic Manager is implied by Dental Administrator)
DENTIST_WORKSPACE_GROUPS = 'dental_base.group_dental_dentist,dental_base.group_dental_manager'


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _get_dental_dentist_profile(self):
        """The active employee linked to this user with Dental Role = Dentist.

        Only employees of the user's own companies count; the current company's
        profile wins when the user is a dentist in several branches.
        """
        self.ensure_one()
        if not self.id:
            return self.env['hr.employee']
        employees = self.env['hr.employee'].sudo().with_context(active_test=True).search([
            ('user_id', '=', self.id),
            ('dental_role', '=', 'dentist'),
            ('company_id', 'in', self.sudo().company_ids.ids),
        ], order='id')
        return employees.filtered(lambda e: e.company_id == self.env.company)[:1] or employees[:1]

    def _has_dentist_workspace_access(self):
        """Dentist Workspace needs BOTH a dental permission (Dentist / Clinic Manager /
        Dental Administrator) AND a linked employee whose Dental Role is Dentist."""
        self.ensure_one()
        return bool(
            self.active
            and self.has_groups(DENTIST_WORKSPACE_GROUPS)
            and self._get_dental_dentist_profile()
        )
