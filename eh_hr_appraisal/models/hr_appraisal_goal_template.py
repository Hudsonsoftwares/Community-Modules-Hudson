from odoo import models, fields

class HrAppraisalGoalTemplate(models.Model):
    _name = "hr.appraisal.goal.template"
    _description = "Goal Template"

    name = fields.Char("Name", required=True)
    parent_id = fields.Many2one('hr.appraisal.goal.template', string="Parent Goal Template", help="You can define this goal to be part of another one")
    timing = fields.Integer("Usual Timing", default=0, help="in months")
    skill_ids = fields.Many2many('hr.skill', string="Expected Skills")
    tag_ids = fields.Many2many('hr.appraisal.goal.tag', string="Tags")
    description = fields.Html("Description", placeholder="Provide visible information on the goal, how the employee can achieve it. Which benefit he will get from it. Maybe some process or steps to help her/him.")
    sub_goal_ids = fields.One2many('hr.appraisal.goal.template', 'parent_id', string="Sub-Goals")
