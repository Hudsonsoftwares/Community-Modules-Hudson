from odoo import api, fields, models, _
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta

class HrAppraisal(models.Model):
    _name = "hr.appraisal"
    _description = "Employee Appraisal"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = "date_appraisal desc, id desc"

    def _get_default_employee(self):
        return self.env.user.employee_id

    name = fields.Char(string="Reference", required=True, copy=False, readonly=True, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string="Employee", required=True, default=_get_default_employee, index=True, tracking=True)
    manager_id = fields.Many2one('hr.employee', string="Manager", related="employee_id.parent_id", store=True, readonly=False, tracking=True)
    department_id = fields.Many2one('hr.department', string="Department", related="employee_id.department_id", store=True, readonly=False)
    job_id = fields.Many2one('hr.job', string="Job Position", related="employee_id.job_id", store=True, readonly=False)
    
    date_appraisal = fields.Date(string="Appraisal Date", required=True, default=fields.Date.context_today, tracking=True)
    date_next = fields.Date(string="Next Appraisal Date", tracking=True)
    
    rating = fields.Selection([
        ('poor', 'Poor'),
        ('average', 'Average'),
        ('good', 'Good'),
        ('excellent', 'Excellent')
    ], string="Final Rating", tracking=True)
    
    notes = fields.Html(string="Notes")
    
    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company)
    appraiser_ids = fields.Many2many('hr.employee', 'appraisal_appraiser_rel', 'appraisal_id', 'employee_id', string='Appraisers')
    rating_id = fields.Many2one('hr.appraisal.scale', string="Evaluation")
    template_id = fields.Many2one('hr.appraisal.template', string="Template")
    
    avatar_128 = fields.Image(related='employee_id.avatar_128', string="Avatar 128")
    avatar_1920 = fields.Image(related='employee_id.avatar_1920', string="Avatar")

    employee_feedback = fields.Html(string="Employee's Feedback")
    manager_feedback = fields.Html(string="Manager's Feedback")
    employee_feedback_published = fields.Boolean(string="Shared to Appraisers", default=False)
    manager_feedback_published = fields.Boolean(string="Shared to Employee", default=False)
    private_note = fields.Html(string="Private Note")

    state = fields.Selection([
        ('draft', 'Draft'),
        ('ongoing', 'Ongoing'),
        ('done', 'Done'),
        ('cancel', 'Cancelled')
    ], string="Status", default='draft', required=True, tracking=True)

    goal_ids = fields.One2many('hr.appraisal.goal', 'appraisal_id', string="Goals")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('hr.appraisal') or _('New')
        return super().create(vals_list)

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            if not self.employee_feedback and self.template_id.employee_feedback_template:
                self.employee_feedback = self.template_id.employee_feedback_template
            if not self.manager_feedback and self.template_id.manager_feedback_template:
                self.manager_feedback = self.template_id.manager_feedback_template

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id and self.employee_id.parent_id:
            self.appraiser_ids = [(4, self.employee_id.parent_id.id)]

    def action_confirm(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_("Only draft appraisals can be confirmed."))
            record.state = 'ongoing'

    def action_done(self):
        for record in self:
            if record.state != 'ongoing':
                raise UserError(_("Only ongoing appraisals can be marked as done."))
            record.state = 'done'
            employee = record.employee_id
            if employee and employee.company_id.appraisal_plan:
                # Find how many appraisals this employee has had
                appraisals_count = self.search_count([('employee_id', '=', employee.id), ('state', '=', 'done')])
                
                # Logic: If 1st done appraisal -> set next based on appraisal_plan_next_month
                # If >= 2 done appraisals -> set next based on appraisal_plan_recurring_month
                months_to_add = employee.company_id.appraisal_plan_recurring_month
                if appraisals_count == 1:
                    months_to_add = employee.company_id.appraisal_plan_next_month
                
                new_date = fields.Date.today() + relativedelta(months=months_to_add)
                record.date_next = new_date
                # Do not overwrite if manually configured later, but here we update it because they just completed one.
                employee.next_appraisal_date = new_date
            elif record.date_appraisal and not record.date_next:
                record.date_next = record.date_appraisal + relativedelta(years=1)
                if employee:
                    employee.next_appraisal_date = record.date_next

    def action_cancel(self):
        for record in self:
            record.state = 'cancel'

    def action_draft(self):
        for record in self:
            record.state = 'draft'

    @api.model
    def _cron_send_reminders(self):
        # Find upcoming appraisals (e.g., in 7 days) and overdue appraisals
        today = fields.Date.today()
        upcoming_date = today + relativedelta(days=7)
        
        # Upcoming
        upcoming_appraisals = self.search([
            ('state', 'in', ['draft', 'ongoing']),
            ('date_appraisal', '=', upcoming_date)
        ])
        for appraisal in upcoming_appraisals:
            appraisal.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=appraisal.manager_id.user_id.id or appraisal.employee_id.user_id.id,
                note=_("Upcoming Appraisal for %s", appraisal.employee_id.name),
                summary=_("Upcoming Appraisal"),
                date_deadline=appraisal.date_appraisal
            )
            
        # Overdue
        overdue_appraisals = self.search([
            ('state', 'in', ['draft', 'ongoing']),
            ('date_appraisal', '<', today)
        ])
        for appraisal in overdue_appraisals:
            # Avoid spamming every day, maybe only schedule if no activity exists for overdue
            existing_activities = self.env['mail.activity'].search_count([
                ('res_id', '=', appraisal.id),
                ('res_model', '=', 'hr.appraisal'),
                ('summary', '=', _("Overdue Appraisal"))
            ])
            if not existing_activities:
                appraisal.activity_schedule(
                    'mail.mail_activity_data_warning',
                    user_id=appraisal.manager_id.user_id.id or appraisal.employee_id.user_id.id,
                    note=_("The appraisal for %s is overdue.", appraisal.employee_id.name),
                    summary=_("Overdue Appraisal"),
                    date_deadline=today
                )

    @api.model
    def _cron_appraisal_automation(self):
        today = fields.Date.today()
        # Find employees whose next appraisal date is today or earlier
        employees = self.env['hr.employee'].search([
            ('next_appraisal_date', '<=', today),
            ('company_id.appraisal_automation', '=', True)
        ])

        for employee in employees:
            # Check if there's already an active appraisal for this employee
            active_appraisal = self.search([
                ('employee_id', '=', employee.id),
                ('state', 'in', ['draft', 'ongoing'])
            ], limit=1)
            
            if not active_appraisal:
                appraisal = self.create({
                    'employee_id': employee.id,
                    'company_id': employee.company_id.id,
                    'date_appraisal': today,
                })
                # Confirm it automatically
                appraisal.action_confirm()
                
                # Notify employee and manager
                appraisal.message_post(
                    body=_("Appraisal automatically created and confirmed based on your Appraisal Plan."),
                    subject=_("Appraisal Created"),
                    partner_ids=[employee.user_id.partner_id.id, employee.parent_id.user_id.partner_id.id]
                )
                appraisal.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=appraisal.manager_id.user_id.id or appraisal.employee_id.user_id.id,
                    note=_("Automated Appraisal for %s", appraisal.employee_id.name),
                    summary=_("Appraisal Created"),
                    date_deadline=today
                )
