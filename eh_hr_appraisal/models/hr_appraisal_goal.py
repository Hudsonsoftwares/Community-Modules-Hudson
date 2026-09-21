from odoo import api, fields, models

class HrAppraisalGoal(models.Model):
    _name = "hr.appraisal.goal"
    _description = "Appraisal Goal"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Goal Name", required=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string="Employee", required=True, tracking=True)
    manager_id = fields.Many2one('hr.employee', string="Manager")
    appraisal_id = fields.Many2one('hr.appraisal', string="Appraisal", domain="[('employee_id', '=', employee_id)]", tracking=True)
    description = fields.Html(string="Description", placeholder="Provide visible information on the goal, how the employee can achieve it. Which benefit he will get from it. Maybe some process or steps to help her/him.")
    deadline = fields.Date(string="Deadline", tracking=True)
    progress = fields.Selection([
        ('0', '0%'),
        ('25', '25%'),
        ('50', '50%'),
        ('75', '75%'),
        ('100', '100%')
    ], string="Progress", default='0', tracking=True)
    tag_ids = fields.Many2many('hr.appraisal.goal.tag', string="Tags")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('done', 'Done')
    ], string="Status", default='draft', required=True, tracking=True)

    @api.onchange('appraisal_id')
    def _onchange_appraisal_id(self):
        if self.appraisal_id and not self.employee_id:
            self.employee_id = self.appraisal_id.employee_id
            
    def action_mark_as_done(self):
        for record in self:
            record.progress = '100'
            record.state = 'done'

    def action_save_as_template(self):
        for record in self:
            self.env['hr.appraisal.goal.template'].create({
                'name': record.name,
                'description': record.description,
                'tag_ids': [(6, 0, record.tag_ids.ids)],
            })
