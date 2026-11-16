from odoo import models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def _filter_visible_menus(self):
        """Hide the whole Dentist Workspace app (root + every submenu, including those
        added by other modules) from users without a linked Dentist employee profile.

        Group-based visibility alone is not enough: holding the Dentist / Manager
        permission does not make a user a doctor. ``load_menus`` and
        ``load_menus_root`` are cached per user; the cache is invalidated when a
        dentist employee link changes (see hr.employee) or the user's groups change.
        """
        menus = super()._filter_visible_menus()
        root = self.env.ref('dental_core.menu_dental_dentist_workspace', raise_if_not_found=False)
        if not root or not menus:
            return menus
        prefix = f'{root.id}/'
        workspace_menus = menus.filtered(lambda m: (m.parent_path or '').startswith(prefix))
        if workspace_menus and not self.env.user._has_dentist_workspace_access():
            menus -= workspace_menus
        return menus
