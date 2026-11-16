from odoo import api, models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @api.model
    def lazy_session_info(self):
        res = super().lazy_session_info()
        employee = self.env.user.employee_id if self.env.user else False
        if employee:
            res['attendance_capture_check_out'] = employee.company_id.attendance_capture_check_out
        return res
