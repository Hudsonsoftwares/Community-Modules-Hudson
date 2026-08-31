# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FsPlanningSlot(models.Model):
    _name = 'fs.planning.slot'
    _description = 'Field Service Planning Slot'
    _order = 'date_start asc, resource_id asc'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']

    name = fields.Char(string='Description')
    active = fields.Boolean(default=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    resource_id = fields.Many2one(
        'hr.employee',
        string='Resource',
        ondelete='cascade',
        index=True,
    )
    role_id = fields.Many2one(
        'fs.planning.role',
        string='Role',
        ondelete='restrict',
        index=True,
    )
    color = fields.Integer(
        related='role_id.color',
        string='Color',
        readonly=True,
    )
    date_start = fields.Datetime(
        string='Start Date',
        required=True,
        index=True,
    )
    date_end = fields.Datetime(
        string='End Date',
        required=True,
        index=True,
    )
    allocated_hours = fields.Float(
        string='Allocated Hours',
        compute='_compute_allocated_hours',
        store=True,
    )
    
    project_id = fields.Many2one(
        'project.project',
        string='Project',
        ondelete='set null',
    )
    task_id = fields.Many2one(
        'project.task',
        string='Task',
        domain="[('project_id', '=?', project_id)]",
        ondelete='set null',
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        ondelete='set null',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Client',
        ondelete='set null',
    )
    attendance_status = fields.Selection([
        ('unmarked', 'Unmarked'),
        ('present', 'Present'),
        ('absent', 'Absent'),
    ], string='Attendance Status', default='unmarked', required=True, tracking=True)
    shift_template_id = fields.Many2one(
        'fs.shift.template',
        string='Shift Template',
        ondelete='set null',
    )
    note = fields.Text(string='Note')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )

    @api.depends('date_start', 'date_end')
    def _compute_allocated_hours(self):
        for slot in self:
            if slot.date_start and slot.date_end:
                delta = slot.date_end - slot.date_start
                slot.allocated_hours = delta.total_seconds() / 3600.0
            else:
                slot.allocated_hours = 0.0

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for slot in self:
            if slot.date_start and slot.date_end and slot.date_start > slot.date_end:
                raise ValidationError(_('Start date must be before end date.'))

    @api.constrains('date_start', 'date_end', 'resource_id')
    def _check_overlap(self):
        if self.env.context.get('force_generate'):
            return
        for slot in self:
            if not slot.resource_id or not slot.date_start or not slot.date_end:
                continue
            domain = [
                ('resource_id', '=', slot.resource_id.id),
                ('id', '!=', slot.id),
                ('date_start', '<', slot.date_end),
                ('date_end', '>', slot.date_start),
            ]
            overlapping = self.env['fs.planning.slot'].search(domain, limit=1)
            if overlapping:
                raise ValidationError(_("Overlap Alert: The employee '%s' is already assigned to a shift from %s to %s that conflicts with this assignment. \n\n(Note: If you assign via the Shift Generation wizard, you will have an option to 'Proceed Anyway' and override this restriction).") % (
                    slot.resource_id.name,
                    overlapping.date_start.strftime('%Y-%m-%d %H:%M'),
                    overlapping.date_end.strftime('%Y-%m-%d %H:%M')
                ))

    @api.onchange('role_id')
    def _onchange_role_id(self):
        if self.role_id and self.resource_id:
            if self.resource_id not in self.role_id.resource_ids:
                self.resource_id = False

    def action_publish(self):
        self.write({'state': 'published'})
        return True

    def action_unpublish(self):
        self.write({'state': 'draft'})


