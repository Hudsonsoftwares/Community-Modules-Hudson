import json
from datetime import timedelta

import odoo.modules.module
from odoo import api, fields, models

from ..const import SENSITIVE_KEYS


def mask_sensitive(data):
    """Return a copy of ``data`` with secrets, OTPs, tokens and Aadhaar masked."""
    if isinstance(data, dict):
        masked = {}
        for key, value in data.items():
            normalized = str(key).lower().replace('_', '')
            if normalized in SENSITIVE_KEYS and value not in (None, '', False):
                masked[key] = '***'
            else:
                masked[key] = mask_sensitive(value)
        return masked
    if isinstance(data, list):
        return [mask_sensitive(item) for item in data]
    return data


def to_log_text(data, limit=100000):
    """Serialize a payload (dict, list, bytes or str) for the log, masked and truncated."""
    if data in (None, '', b''):
        return False
    if isinstance(data, bytes):
        data = data.decode('utf-8', errors='replace')
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return data[:limit]
    text = json.dumps(mask_sensitive(data), indent=2, ensure_ascii=False, default=str)
    return text[:limit]


class AbdmApiLog(models.Model):
    _name = 'abdm.api.log'
    _description = 'ABDM API Log'
    _order = 'id desc'
    _rec_name = 'endpoint'

    direction = fields.Selection([
        ('outgoing', 'Outgoing (we call ABDM)'),
        ('incoming', 'Incoming (ABDM calls us)'),
    ], required=True, index=True)
    environment = fields.Selection([
        ('sandbox', 'Sandbox'),
        ('production', 'Production'),
    ])
    method = fields.Char()
    endpoint = fields.Char(required=True, index=True)
    request_id = fields.Char(string='REQUEST-ID', index=True,
                             help='Unique ID of this HTTP call (REQUEST-ID header).')
    correlation_id = fields.Char(index=True,
                                 help='REQUEST-ID of the original request this callback answers.')
    status_code = fields.Integer(string='HTTP Status')
    state = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
    ], required=True, default='success', index=True)
    duration_ms = fields.Integer(string='Duration (ms)')
    request_headers = fields.Text()
    request_body = fields.Text()
    response_body = fields.Text()
    error_message = fields.Text()
    # No Many2one to abdm.transaction: logs are written in a separate cursor
    # and could not reference a transaction that is not committed yet.
    # Transactions find their logs through request_id / correlation_id.
    user_id = fields.Many2one('res.users', default=lambda self: self.env.uid)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model
    def _log(self, **vals):
        """Write a log line in its own cursor so it survives a rollback of the caller."""
        for key in ('request_headers', 'request_body', 'response_body'):
            if key in vals:
                vals[key] = to_log_text(vals[key])
        if vals.get('error_message'):
            vals['error_message'] = str(vals['error_message'])[:5000]
        if odoo.modules.module.current_test:
            return self.sudo().create(vals)
        with self.env.registry.cursor() as cr:
            env = self.env(cr=cr, su=True)
            record = env[self._name].create(vals)
            record_id = record.id
        return self.browse(record_id)

    @api.model
    def _cron_purge(self):
        days = self.env['ir.config_parameter'].sudo().get_int('abdm_base.log_retention_days', 90)
        if days <= 0:
            return
        limit = fields.Datetime.now() - timedelta(days=days)
        self.sudo().search([('create_date', '<', limit)]).unlink()
