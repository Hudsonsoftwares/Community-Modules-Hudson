from odoo import models, fields, api, _

class AppraisalLaunchWizard(models.TransientModel):
    _name = 'hr.appraisal.launch.wizard'
    _description = 'Launch Appraisal Campaign'

    def _default_employees(self):
        if self.env.context.get('active_model') == 'hr.employee' and self.env.context.get('active_ids'):
            return self.env['hr.employee'].browse(self.env.context.get('active_ids'))
        return False

    employee_ids = fields.Many2many('hr.employee', string="Employees List", default=_default_employees)
    employee_display = fields.Char(string="Employees", compute="_compute_employee_display")
    
    manager_mode = fields.Selection([
        ('manager', "Employee's Manager"),
        ('other', 'Other')
    ], string="Manager", default='manager', required=True,
       help="Select who will be the manager for these appraisals.")
       
    template_id = fields.Many2one('hr.appraisal.template', string="Appraisal Template")
    date_appraisal = fields.Date(string="Appraisal Date", default=fields.Date.context_today, required=True)
    
    no_manager_warning = fields.Char(compute="_compute_no_manager_warning")
    show_warning = fields.Boolean(compute="_compute_no_manager_warning")

    @api.depends('employee_ids')
    def _compute_employee_display(self):
        for rec in self:
            if not rec.employee_ids:
                rec.employee_display = _("All Employees")
            else:
                rec.employee_display = _("%s Selected Employees") % len(rec.employee_ids)

    @api.depends('employee_ids', 'manager_mode')
    def _compute_no_manager_warning(self):
        for rec in self:
            if rec.manager_mode == 'manager':
                employees = rec.employee_ids if rec.employee_ids else self.env['hr.employee'].search([])
                no_manager_emps = employees.filtered(lambda e: not e.parent_id)
                if no_manager_emps:
                    names = ", ".join(no_manager_emps.mapped('name'))
                    rec.no_manager_warning = _("- Appraisals won't be created for the following employees because they don't have a manager: %s") % names
                    rec.show_warning = True
                else:
                    rec.no_manager_warning = ""
                    rec.show_warning = False
            else:
                rec.no_manager_warning = ""
                rec.show_warning = False

    def action_launch(self):
        self.ensure_one()
        appraisal_env = self.env['hr.appraisal']
        employees = self.employee_ids if self.employee_ids else self.env['hr.employee'].search([])
        
        if self.manager_mode == 'manager':
            employees = employees.filtered(lambda e: e.parent_id)
            
        created_count = 0
        for employee in employees:
            existing = appraisal_env.search([
                ('employee_id', '=', employee.id),
                ('state', 'in', ['draft', 'ongoing'])
            ], limit=1)
            
            if not existing:
                appraisal_env.create({
                    'employee_id': employee.id,
                    'date_appraisal': self.date_appraisal,
                    'template_id': self.template_id.id if self.template_id else False,
                })
                created_count += 1
                
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Campaign Launched'),
                'message': _('Successfully scheduled %s appraisals.', created_count),
                'type': 'success',
                'sticky': False,
            }
        }
