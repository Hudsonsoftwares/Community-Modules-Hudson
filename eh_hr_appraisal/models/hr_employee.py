from odoo import api, fields, models
from dateutil.relativedelta import relativedelta

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    next_appraisal_date = fields.Date(
        string='Next Appraisal Date',
        tracking=True,
        help="The date of the next appraisal is computed by the appraisal plan's dates (first appraisal + periodicity)."
    )

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        for employee in employees:
            if employee.company_id.appraisal_plan and not employee.next_appraisal_date:
                # Assuming create_date is the closest to recruitment date if first_contract_date is not available
                base_date = employee.create_date.date() if employee.create_date else fields.Date.today()
                months_to_add = employee.company_id.appraisal_plan_first_month
                employee.next_appraisal_date = base_date + relativedelta(months=months_to_add)
        return employees
