from odoo import api, fields, models

BOARD_STATES = [
    ('planned', 'Planned'),
    ('in_progress', 'In Progress'),
    ('done', 'Done'),
]


class ProjectTaskType(models.Model):
    _inherit = 'project.task.type'

    dental_board_state = fields.Selection(
        BOARD_STATES, string='Treatment Board Column', index=True,
        help='Column of a treatment plan board: phases in this stage are planned, in progress or done.')

    @api.model
    def _dental_board_stages(self):
        """The board columns of every treatment plan, in order (created by this module's data)."""
        return self.search([('dental_board_state', '!=', False)], order='sequence, id')

    @api.model
    def _dental_stage_for(self, board_state):
        return self.search([('dental_board_state', '=', board_state)], order='sequence, id', limit=1)
