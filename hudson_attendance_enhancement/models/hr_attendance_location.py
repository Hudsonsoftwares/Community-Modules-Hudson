from odoo import models, fields

class HrAttendanceLocation(models.Model):
    _name = 'hr.attendance.location'
    _description = 'Attendance Allowed Location'

    name = fields.Char('Location Name', required=True)
    latitude = fields.Float('Latitude', required=True, digits=(10, 7))
    longitude = fields.Float('Longitude', required=True, digits=(10, 7))
    radius = fields.Float('Radius (meters)', required=True, default=50.0)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
