from odoo import fields, models

class HrAppraisalTemplate(models.Model):
    _name = "hr.appraisal.template"
    _description = "Appraisal Template"

    name = fields.Char(string="Short Name", required=True, translate=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    department_ids = fields.Many2many('hr.department', string="Departments")
    survey_id = fields.Many2one('survey.survey', string="360 Feedback Survey")
    employee_feedback_template = fields.Html(string="Employee's Feedback")
    manager_feedback_template = fields.Html(string="Manager's Feedback")
