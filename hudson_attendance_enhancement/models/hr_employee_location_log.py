from odoo import models, fields, api

class HrEmployeeLocationLog(models.Model):
    _name = 'hr.employee.location.log'
    _description = 'Employee Location Tracking Log'
    _order = 'timestamp desc'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade', index=True)
    attendance_id = fields.Many2one('hr.attendance', string='Attendance Session', ondelete='set null', index=True)
    timestamp = fields.Datetime('Timestamp', default=fields.Datetime.now, index=True)
    latitude = fields.Float('Latitude', required=True, digits=(10, 7))
    longitude = fields.Float('Longitude', required=True, digits=(10, 7))
    accuracy = fields.Float('Accuracy (meters)')
    distance_from_home = fields.Float('Distance from Home (m)')
    distance_from_checkin = fields.Float('Distance from Check-In (m)')
    address = fields.Char('Location / Address')
    ip_address = fields.Char('IP Address')
    status = fields.Selection([
        ('at_home', 'At Home'),
        ('near_home', 'Near Home'),
        ('offsite', 'Offsite / Away'),
    ], string='Status', default='at_home')
