from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    attendance_radius_punching = fields.Boolean(
        string="Enable Radius Punching",
        related='company_id.attendance_radius_punching',
        readonly=False,
    )
    # The view will provide a link to configure locations
