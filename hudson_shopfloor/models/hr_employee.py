# -*- coding: utf-8 -*-
from odoo import models, api

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.model
    def check_shopfloor_pin(self, employee_id, pin):
        employee = self.sudo().browse(employee_id)
        if not employee.exists():
            return False
            
        # If employee has no pin, allow empty pin login
        if not employee.pin and not pin:
            return True
            
        return employee.pin == pin
