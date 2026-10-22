from odoo import models, fields, api

class MaintenanceEquipment(models.Model):
    _inherit = 'maintenance.equipment'

    previous_employee_id = fields.Many2one('hr.employee', string='Previous Employee', tracking=True)
    transfer_date = fields.Date(string='Transfer Date', tracking=True)

    def write(self, vals):
        if 'employee_id' in vals:
            for record in self:
                if record.employee_id and record.employee_id.id != vals['employee_id']:
                    vals['previous_employee_id'] = record.employee_id.id
                    vals['transfer_date'] = fields.Date.today()
        return super(MaintenanceEquipment, self).write(vals)
