from odoo import models, fields, api

class DmsAccessGroup(models.Model):
    _inherit = 'dms.access.group'

    dms_manager_user_ids = fields.Many2many(
        'res.users', 
        compute='_compute_dms_manager_user_ids',
        string="DMS Manager Users"
    )

    def _compute_dms_manager_user_ids(self):
        manager_group = self.env.ref('dms.group_dms_manager', raise_if_not_found=False)
        manager_users = manager_group.all_user_ids if manager_group else self.env['res.users']
        for record in self:
            record.dms_manager_user_ids = manager_users

    @api.depends("group_ids", "explicit_user_ids")
    def _compute_users(self):
        for record in self:
            users = record.explicit_user_ids
            if record.group_ids:
                users |= self.env["res.users"].search(
                    [("group_ids", "in", record.group_ids.ids)]
                )
            record.users = users

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Remove the current user from being added automatically to explicit_user_ids
        if 'explicit_user_ids' in res:
            if isinstance(res['explicit_user_ids'], list) and res['explicit_user_ids'] and isinstance(res['explicit_user_ids'][0], tuple):
                # Format is [(6, 0, [ids])]
                for cmd in res['explicit_user_ids']:
                    if cmd[0] == 6 and self.env.uid in cmd[2]:
                        cmd[2].remove(self.env.uid)
            elif isinstance(res['explicit_user_ids'], list) and self.env.uid in res['explicit_user_ids']:
                res['explicit_user_ids'].remove(self.env.uid)
        return res
