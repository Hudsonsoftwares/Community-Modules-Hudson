# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from odoo import models, api
from datetime import datetime, time

class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.employee_id and record.check_in:
                # Find shifts for this employee today
                check_in_date = record.check_in.date()
                datetime_start = datetime.combine(check_in_date, time.min)
                datetime_end = datetime.combine(check_in_date, time.max)
                
                slots = self.env['fs.planning.slot'].search([
                    ('resource_id', '=', record.employee_id.id),
                    ('date_start', '>=', datetime_start),
                    ('date_start', '<=', datetime_end),
                    ('state', '=', 'published')
                ])
                for slot in slots:
                    slot.attendance_status = 'present'
        return records
