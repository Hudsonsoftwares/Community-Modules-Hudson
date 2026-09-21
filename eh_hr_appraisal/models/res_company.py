from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    appraisal_plan = fields.Boolean(string='Appraisal Plans', default=True)
    appraisal_plan_first_month = fields.Integer(string='First Appraisal in (months)', default=6)
    appraisal_plan_next_month = fields.Integer(string='Second Appraisal in (months)', default=6)
    appraisal_plan_recurring_month = fields.Integer(string='Recurring Appraisal in (months)', default=12)

    appraisal_360_feedback = fields.Boolean(string='360 Feedback', default=True)
    appraisal_automation = fields.Boolean(string='Appraisals Automation', default=True)
