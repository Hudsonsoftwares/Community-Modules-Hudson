from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    dental_plan_id = fields.Many2one('dental.treatment.plan', string='Treatment Plan', index='btree_not_null',
                                     copy=False, ondelete='set null')

    def action_dental_open_plan(self):
        self.ensure_one()
        return self.dental_plan_id.action_open_form()

    def action_view_tasks(self):
        # A treatment plan's project opens on its phase board
        if len(self) == 1 and self.dental_plan_id:
            return self.dental_plan_id.action_dental_open_board()
        return super().action_view_tasks()
