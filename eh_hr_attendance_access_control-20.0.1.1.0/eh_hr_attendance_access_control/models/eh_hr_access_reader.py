# -*- encoding: utf-8 -*-
import json
import logging
import time

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class EhHrAccessReader(models.Model):
    _name = 'eh.hr.access.reader'
    _description = 'Access Reader'
    _inherit = ['mail.thread']
    _order = 'zone_id, name'

    name = fields.Char(string='Reader name', required=True, tracking=True)
    zone_id = fields.Many2one(
        'eh.hr.access.zone',
        string='Zone',
        required=True,
        ondelete='cascade',
        tracking=True,
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='zone_id.company_id',
        store=True,
        index=True,
    )
    webhook_url = fields.Char(
        string='Webhook URL',
        required=True,
        tracking=True,
        help="HTTP endpoint that the bridge service exposes for unlock commands. We POST a JSON body to this URL.",
    )
    bearer_token = fields.Char(
        string='Bearer token',
        groups='eh_hr_attendance_base.group_eh_hr_admin',
        help="Optional. When set, the module sends 'Authorization: Bearer ...' on every webhook call.",
    )
    auto_relock_seconds = fields.Integer(
        string='Auto-relock (seconds)',
        default=5,
        help="Sent to the bridge as 'auto_relock_seconds' so the door can re-lock without a second call.",
    )
    timeout_seconds = fields.Integer(
        string='HTTP timeout (seconds)',
        default=4,
    )
    active = fields.Boolean(default=True, tracking=True)
    last_unlock_at = fields.Datetime(string='Last unlock', readonly=True)
    last_status = fields.Selection(
        [
            ('ok', 'OK'),
            ('denied', 'Denied'),
            ('error', 'Error'),
            ('never', 'Never called'),
        ],
        string='Last status',
        default='never',
        readonly=True,
    )
    last_response = fields.Text(string='Last response', readonly=True)

    @api.constrains('webhook_url')
    def _check_url(self):
        for record in self:
            if not record.webhook_url:
                raise ValidationError(_("Webhook URL is required."))
            if not (record.webhook_url.startswith('http://') or record.webhook_url.startswith('https://')):
                raise ValidationError(_("Webhook URL must start with http:// or https://."))

    def _call_webhook(self, payload):
        """Synchronous HTTP POST to the reader's webhook URL.

        Returns (status_string, response_text). status_string is one of
        'ok', 'denied', 'error'. The bridge service is expected to
        return JSON `{ok: bool, message?: str}` or any 2xx for
        success; 4xx for denied; 5xx or network failure for error.
        """
        self.ensure_one()
        try:
            import requests  # noqa: WPS433
        except ImportError:
            return 'error', 'requests library not installed'

        headers = {'Content-Type': 'application/json'}
        if self.bearer_token:
            headers['Authorization'] = 'Bearer %s' % self.bearer_token

        body = dict(payload, auto_relock_seconds=self.auto_relock_seconds)
        try:
            resp = requests.post(
                self.webhook_url,
                data=json.dumps(body),
                headers=headers,
                timeout=self.timeout_seconds or 4,
            )
        except Exception as err:
            _logger.warning('Access reader %s webhook failed: %s', self.name, err)
            return 'error', str(err)[:1000]

        if 200 <= resp.status_code < 300:
            return 'ok', resp.text[:1000]
        if 400 <= resp.status_code < 500:
            return 'denied', resp.text[:1000]
        return 'error', '%s %s' % (resp.status_code, resp.text[:1000])

    def trigger_unlock(self, *, employee, reason=''):
        """Public API. Called by the access trigger controller after a
        match. Returns (status, ms_elapsed, response_text).
        """
        self.ensure_one()
        started = time.time()
        payload = {
            'action': 'unlock',
            'employee_id': employee.id if employee else None,
            'employee_name': employee.name if employee else '',
            'zone_id': self.zone_id.id,
            'zone_code': self.zone_id.code,
            'reason': reason or 'face_match',
        }
        status, response = self._call_webhook(payload)
        ms_elapsed = int((time.time() - started) * 1000)
        self.sudo().write({
            'last_unlock_at': fields.Datetime.now(),
            'last_status': status,
            'last_response': response,
        })
        return status, ms_elapsed, response

    def action_test_unlock(self):
        """Manual trigger from the form view. Used during commissioning
        to verify the bridge is reachable and authorised."""
        for record in self:
            status, ms, response = record.trigger_unlock(
                employee=self.env.user.employee_id if self.env.user.employee_id else None,
                reason='manual_test',
            )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Reader test'),
                    'message': _("Status: %(s)s, %(ms)s ms. %(resp)s") % {
                        's': status, 'ms': ms, 'resp': response[:200] if response else '',
                    },
                    'type': 'success' if status == 'ok' else 'warning',
                    'sticky': True,
                },
            }
