# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class FieldServiceStopWizard(models.TransientModel):
    _name = 'field.service.stop.wizard'
    _description = 'Stop Timer Wizard'

    order_id = fields.Many2one(
        'field.service.order',
        string='Field Service Order',
        required=True,
    )
    start_time = fields.Datetime(string='Start Time', readonly=True)
    end_time = fields.Datetime(string='End Time', readonly=True)
    duration = fields.Float(
        string='Duration (Hours)',
        readonly=False,
        help='Elapsed time in hours. You can adjust this value.',
    )
    description = fields.Char(
        string='Work Description',
        help='Describe the work performed during this session.',
    )
    action_type = fields.Selection([
        ('pause', 'Pause'),
        ('stop', 'Stop & Complete'),
    ], string='Action', default='pause')

    def action_confirm(self):
        """Save the timesheet entry and update the order."""
        self.ensure_one()
        order = self.order_id
        if not order.timer_start:
            raise UserError(_('Timer is not running!'))

        # Create timesheet entry
        self.env['field.service.timesheet'].create({
            'order_id': order.id,
            'user_id': order.employee_id.user_id.id if order.employee_id.user_id else self.env.user.id,
            'date': fields.Date.context_today(self),
            'description': self.description or _('Timer session'),
            'duration': self.duration,
            'start_time': self.start_time,
            'end_time': self.end_time,
        })

        # Update order state
        if self.action_type == 'stop':
            order.write({
                'timer_start': False,
                'state': 'done',
                'date_end': fields.Datetime.now(),
            })
            # Move to closing stage
            close_stage = self.env['field.service.stage'].search(
                [('is_close', '=', True)], limit=1
            )
            if close_stage:
                order.stage_id = close_stage
        else:
            order.write({
                'timer_start': False,
                'state': 'paused',
                'last_paused_time': fields.Datetime.now(),
            })
        return True
