from odoo import models, fields

class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    check_in_photo = fields.Image(string="Check In Photo", max_width=1024, max_height=1024)
    check_out_photo = fields.Image(string="Check Out Photo", max_width=1024, max_height=1024)
