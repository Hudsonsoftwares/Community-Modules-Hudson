# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FsShiftTemplate(models.Model):
    _name = 'fs.shift.template'
    _description = 'Field Service Shift Template'
    _order = 'start_time asc, role_id asc'

    name = fields.Char(string='Name', required=True, translate=True)
    active = fields.Boolean(default=True)
    role_id = fields.Many2one(
        'fs.planning.role',
        string='Role',
        ondelete='restrict',
    )
    def _get_time_selection(self):
        selection = []
        for hour in range(0, 24):
            for minute in (0, 30):
                float_val = hour + (minute / 60.0)
                time_str = f"{hour if hour > 0 and hour <= 12 else (hour - 12 if hour > 12 else 12)}:{minute:02d} {'AM' if hour < 12 else 'PM'}"
                selection.append((str(float_val), time_str))
        return selection

    start_time_select = fields.Selection(
        selection='_get_time_selection',
        string='Start Time',
        required=True,
        default='8.0',
    )
    end_time_select = fields.Selection(
        selection='_get_time_selection',
        string='End Time',
        required=True,
        default='17.0',
    )

    start_time = fields.Float(
        string='Start Time (Float)',
        compute='_compute_times_from_select',
        store=True,
    )
    end_time = fields.Float(
        string='End Time (Float)',
        compute='_compute_times_from_select',
        store=True,
    )

    @api.depends('start_time_select', 'end_time_select')
    def _compute_times_from_select(self):
        for template in self:
            template.start_time = float(template.start_time_select) if template.start_time_select else 0.0
            template.end_time = float(template.end_time_select) if template.end_time_select else 0.0
    duration = fields.Float(
        string='Duration',
        compute='_compute_duration',
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
    note = fields.Text(string='Note')

    @api.depends('start_time', 'end_time')
    def _compute_duration(self):
        for template in self:
            if template.start_time and template.end_time:
                duration = template.end_time - template.start_time
                template.duration = duration if duration > 0 else 24.0 + duration
            else:
                template.duration = 0.0

    @api.constrains('start_time', 'end_time')
    def _check_time_range(self):
        for template in self:
            if template.start_time < 0 or template.start_time >= 24:
                raise ValidationError(_('Start Time must be between 0 and 24.'))
            if template.end_time < 0 or template.end_time >= 24:
                raise ValidationError(_('End Time must be between 0 and 24.'))
