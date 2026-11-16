from odoo import models


class DentalCase(models.Model):
    _inherit = 'dental.case'

    def action_new_treatment_plan(self):
        """A new plan opens straight on its board: add one card per phase."""
        action = super().action_new_treatment_plan()
        plan = self.env['dental.treatment.plan'].browse(action.get('res_id'))
        return plan.action_dental_open_board() if plan else action
