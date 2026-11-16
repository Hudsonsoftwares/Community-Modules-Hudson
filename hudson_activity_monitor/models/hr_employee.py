from odoo import _, api, fields, models
from odoo.exceptions import AccessError

GROUP_USER = 'hudson_activity_monitor.group_activity_user'
GROUP_ADMIN = 'hudson_activity_monitor.group_activity_admin'
STATUS_PRIORITY = ['active', 'idle', 'locked', 'paused', 'offline', 'pending', 'revoked']


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # All fields carry a group: in Odoo 20 hr.employee fields without groups that are
    # missing on hr.employee.public raise AccessError for non-HR users.
    activity_monitoring_enabled = fields.Boolean(
        'Activity Monitoring', groups=GROUP_ADMIN,
        help="When disabled, paired devices stop tracking (the agent pauses).")
    activity_consent_date = fields.Date(
        'Consent Date', groups=GROUP_ADMIN,
        help="Date the employee accepted the monitoring policy.")
    activity_device_ids = fields.One2many('hr.activity.device', 'employee_id', 'Devices', groups=GROUP_ADMIN)
    activity_status = fields.Selection([
        ('active', 'Active'), ('idle', 'Idle'), ('locked', 'Locked'), ('paused', 'Paused'),
        ('offline', 'Offline'), ('pending', 'Waiting for pairing'), ('revoked', 'Revoked'),
        ('none', 'No device'),
    ], 'Live Status', compute='_compute_activity_status', groups=GROUP_ADMIN)
    activity_today_hours = fields.Float('Active Today', compute='_compute_activity_today', groups=GROUP_ADMIN)

    @api.depends('activity_device_ids.status')
    def _compute_activity_status(self):
        for employee in self:
            statuses = employee.activity_device_ids.mapped('status')
            employee.activity_status = min(statuses, key=STATUS_PRIORITY.index) if statuses else 'none'

    def _compute_activity_today(self):
        today = fields.Date.context_today(self)
        rows = self.env['hr.activity.daily'].sudo()._read_group(
            [('employee_id', 'in', self.ids), ('date', '=', today)], ['employee_id'], ['active_hours:sum'])
        hours = {employee.id: total for employee, total in rows}
        for employee in self:
            employee.activity_today_hours = hours.get(employee.id, 0.0)

    def _activity_check_manage(self):
        """Only Activity Monitor administrators pair devices and change monitoring.
        Note: non-HR users have no ACL on hr.employee in Odoo 20, so no check_access here."""
        if not (self.env.su or self.env.user.has_group(GROUP_ADMIN)):
            raise AccessError(_("Only Activity Monitor administrators can manage activity monitoring."))

    def _activity_grant_user_role(self):
        """A monitored employee's login gets the Activity Monitor 'User' role, so the
        agent's "Open my activity" link works for them (they still don't see the app)."""
        group = self.env.ref(GROUP_USER)
        users = self.sudo().user_id.filtered(lambda u: group not in u.all_group_ids)
        if users:
            users.write({'group_ids': [(4, group.id)]})

    def action_activity_pair_device(self):
        """Create a pending device with a one-time pairing code and show it."""
        self.ensure_one()
        self._activity_check_manage()
        # Re-use a code that is still waiting instead of piling up pending devices.
        device = self.env['hr.activity.device'].sudo().search([
            ('employee_id', '=', self.id), ('state', '=', 'pending'),
            ('pairing_expiry', '>', fields.Datetime.now())], limit=1)
        if not device:
            device = self.env['hr.activity.device'].create({'employee_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'name': _("Pair a device for %s", self.sudo().name),
            'res_model': 'hr.activity.device',
            'res_id': device.id,
            'view_mode': 'form',
            'views': [(self.env.ref('hudson_activity_monitor.hr_activity_device_view_form').id, 'form')],
            'target': 'new',
        }

    def action_open_activity(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'hudson_activity_monitor.action_hr_activity_daily')
        action['domain'] = [('employee_id', '=', self.id)]
        action['context'] = {'search_default_last_30_days': 1}
        action['display_name'] = _("Activity - %s", self.name)
        return action
