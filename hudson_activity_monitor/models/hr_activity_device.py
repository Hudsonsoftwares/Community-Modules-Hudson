import hashlib
import secrets
from datetime import timedelta

from odoo import _, api, fields, models

from .hr_activity_span import SPAN_STATES

PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I
PAIRING_VALIDITY = timedelta(hours=24)
PARAM = 'hudson_activity_monitor.'


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def get_settings(env):
    """Monitoring settings stored as system parameters (booleans default to False)."""
    icp = env['ir.config_parameter'].sudo()
    return {
        'idle_minutes': icp.get_int(PARAM + 'idle_minutes', 5) or 5,
        'upload_interval': icp.get_int(PARAM + 'upload_interval', 120) or 120,
        'hide_titles': icp.get_bool(PARAM + 'hide_titles'),
        'private_apps': [p.strip() for p in icp.get_str(PARAM + 'private_apps').split(',') if p.strip()],
        'only_checked_in': icp.get_bool(PARAM + 'only_checked_in'),
        'block_quit': icp.get_bool(PARAM + 'block_quit'),
        'retention_days': icp.get_int(PARAM + 'retention_days', 90) or 90,
        'public_url': (icp.get_str(PARAM + 'public_url') or icp.get_str('web.base.url')).rstrip('/'),
    }


class HrActivityDevice(models.Model):
    _name = 'hr.activity.device'
    _description = 'Activity Tracking Device'
    _order = 'last_seen desc, id desc'

    name = fields.Char('Device', required=True, default=lambda self: _('New device'))
    employee_id = fields.Many2one('hr.employee', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='employee_id.company_id', store=True, index=True)
    state = fields.Selection([
        ('pending', 'Waiting for pairing'),
        ('paired', 'Paired'),
        ('revoked', 'Revoked'),
    ], default='pending', required=True, readonly=True)
    pairing_code = fields.Char(copy=False, readonly=True, index=True)
    pairing_expiry = fields.Datetime(copy=False, readonly=True)
    token_hash = fields.Char(copy=False, index=True, groups='base.group_system')
    device_uid = fields.Char('Device ID', index=True, readonly=True)
    os_name = fields.Char('Operating System', readonly=True)
    os_user = fields.Char('OS User', readonly=True)
    agent_version = fields.Char(readonly=True)
    paired_on = fields.Datetime(readonly=True)
    last_seen = fields.Datetime(readonly=True)
    last_state = fields.Selection(SPAN_STATES, readonly=True)
    status = fields.Selection([
        ('active', 'Active'),
        ('idle', 'Idle'),
        ('locked', 'Locked'),
        ('paused', 'Paused'),
        ('offline', 'Offline'),
        ('pending', 'Waiting for pairing'),
        ('revoked', 'Revoked'),
    ], compute='_compute_status')
    server_url = fields.Char('Server URL', compute='_compute_server_url',
                             help="Enter this address in the agent's pairing window.")

    @api.depends('state', 'last_seen', 'last_state')
    def _compute_status(self):
        settings = get_settings(self.env)
        cutoff = fields.Datetime.now() - timedelta(seconds=settings['upload_interval'] * 2 + 60)
        for device in self:
            if device.state != 'paired':
                device.status = device.state
            elif not device.last_seen or device.last_seen < cutoff:
                device.status = 'offline'
            elif not device.employee_id.activity_monitoring_enabled:
                device.status = 'paused'
            else:
                device.status = device.last_state or 'active'

    def _compute_server_url(self):
        url = f"{get_settings(self.env)['public_url']}?db={self.env.cr.dbname}"
        for device in self:
            device.server_url = url

    @api.model_create_multi
    def create(self, vals_list):
        """Managers create (pair) devices for their team; the record itself is
        created as superuser after that check, so no create ACL is needed."""
        employees = self.env['hr.employee'].browse({v.get('employee_id') for v in vals_list if v.get('employee_id')})
        employees._activity_check_manage()
        for vals in vals_list:
            vals.setdefault('pairing_code', self._new_pairing_code())
            vals.setdefault('pairing_expiry', fields.Datetime.now() + PAIRING_VALIDITY)
            vals['state'] = 'pending'
        devices = super(HrActivityDevice, self.sudo()).create(vals_list)
        devices.employee_id.filtered(lambda e: not e.activity_monitoring_enabled).write(
            {'activity_monitoring_enabled': True})
        devices.employee_id._activity_grant_user_role()
        return devices.with_env(self.env)

    @staticmethod
    def _new_pairing_code():
        raw = ''.join(secrets.choice(PAIRING_ALPHABET) for _i in range(8))
        return f"{raw[:4]}-{raw[4:]}"

    # ------------------------------------------------------------ actions
    def _check_manager(self):
        self.employee_id._activity_check_manage()

    def action_revoke(self):
        self._check_manager()
        self.sudo().write({'state': 'revoked', 'token_hash': False, 'pairing_code': False})

    def action_new_code(self):
        self._check_manager()
        for device in self.sudo():
            device.write({'pairing_code': self._new_pairing_code(),
                          'pairing_expiry': fields.Datetime.now() + PAIRING_VALIDITY})

    # -------------------------------------------------------- agent API
    @api.model
    def _pair(self, code, info):
        """Exchange a one-time pairing code for a device token. Returns (device, token)."""
        code = (code or '').strip().upper().replace(' ', '')
        if len(code) == 8 and '-' not in code:
            code = f"{code[:4]}-{code[4:]}"
        device = self.sudo().search([
            ('state', '=', 'pending'),
            ('pairing_code', '=', code),
            ('pairing_expiry', '>', fields.Datetime.now()),
        ], limit=1)
        if not device or not code:
            return None, None
        token = secrets.token_urlsafe(32)
        device_uid = str(info.get('device_uid') or '')[:64]
        if device_uid:
            # Re-pairing the same computer replaces its previous registration.
            self.sudo().search([('device_uid', '=', device_uid), ('state', '=', 'paired')]).write(
                {'state': 'revoked', 'token_hash': False})
        device.write({
            'state': 'paired',
            'token_hash': hash_token(token),
            'pairing_code': False,
            'pairing_expiry': False,
            'paired_on': fields.Datetime.now(),
            'last_seen': fields.Datetime.now(),
            'device_uid': device_uid,
            'name': str(info.get('hostname') or device.name)[:128],
            'os_name': str(info.get('os') or '')[:128],
            'os_user': str(info.get('os_user') or '')[:128],
            'agent_version': str(info.get('agent_version') or '')[:32],
        })
        return device, token

    @api.model
    def _authenticate(self, token):
        if not token:
            return self.browse()
        return self.sudo().search([
            ('token_hash', '=', hash_token(token)),
            ('state', '=', 'paired'),
            ('employee_id.active', '=', True),
        ], limit=1)

    def _agent_config(self):
        """Settings pushed to the agent in every response."""
        self.ensure_one()
        settings = get_settings(self.env)
        employee = self.employee_id
        enabled = bool(employee.activity_monitoring_enabled)
        if enabled and settings['only_checked_in']:
            enabled = employee.attendance_state == 'checked_in'
        return {
            'tracking_enabled': enabled,
            'idle_threshold': settings['idle_minutes'] * 60,
            'upload_interval': settings['upload_interval'],
            'capture_titles': not settings['hide_titles'],
            'private_apps': settings['private_apps'],
            'allow_quit': not settings['block_quit'],
            'dashboard_url': f"{settings['public_url']}/odoo/action-hudson_activity_monitor.action_hr_activity_daily_my",
        }

    def _ingest(self, payload_spans, agent_version=None):
        """Upsert spans sent by the agent. Returns (accepted, rejected)."""
        self.ensure_one()
        result = self.env['hr.activity.span'].sudo()._ingest_for_device(self, payload_spans)
        vals = {'last_seen': fields.Datetime.now()}
        if agent_version:
            vals['agent_version'] = str(agent_version)[:32]
        if result['last_state']:
            vals['last_state'] = result['last_state']
        self.sudo().write(vals)
        return result['accepted'], result['rejected']
