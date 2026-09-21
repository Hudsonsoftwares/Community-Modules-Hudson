from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    attendance_radius_punching = fields.Boolean(string="Enable Radius Punching", default=False)
    attendance_location_ids = fields.One2many('hr.attendance.location', 'company_id', string="Allowed Locations")
