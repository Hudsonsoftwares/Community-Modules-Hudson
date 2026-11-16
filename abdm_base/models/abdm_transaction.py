from datetime import timedelta

from odoo import api, fields, models

from .abdm_api_log import to_log_text


class AbdmTransaction(models.Model):
    """One asynchronous ABDM exchange.

    Most ABDM V3 APIs answer "202 Accepted" at once and send the real result
    later to our callback URL, carrying the original REQUEST-ID in
    ``response.requestId``. A transaction stores that REQUEST-ID so the
    callback can be matched to what we asked, and to the record that asked it.
    """
    _name = 'abdm.transaction'
    _description = 'ABDM Transaction'
    _order = 'id desc'
    _rec_name = 'request_id'

    operation = fields.Char(required=True, index=True,
                            help='Technical name of the flow, e.g. bridge.url or hip.link.')
    request_id = fields.Char(string='REQUEST-ID', required=True, index=True, copy=False, readonly=True)
    state = fields.Selection([
        ('sent', 'Waiting for ABDM'),
        ('done', 'Done'),
        ('error', 'Error'),
        ('timeout', 'No Answer'),
    ], required=True, default='sent', index=True)
    sent_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    response_date = fields.Datetime(readonly=True)
    callback_path = fields.Char(readonly=True, help='Callback path ABDM used to answer.')
    request_summary = fields.Text(readonly=True, help='Masked copy of what was sent.')
    response_summary = fields.Text(readonly=True, help='Masked copy of what ABDM answered.')
    response_data = fields.Json(readonly=True, help='Raw answer, used by the business flows.')
    context_data = fields.Json(readonly=True, help='What the flow needs when the answer arrives (ids...).')
    error_message = fields.Text(readonly=True)
    res_model = fields.Char(string='Related Model', index=True, readonly=True)
    res_id = fields.Many2oneReference(string='Related Record', model_field='res_model', readonly=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, readonly=True)
    log_count = fields.Integer(compute='_compute_log_count')

    _request_id_uniq = models.Constraint('UNIQUE(request_id)', 'REQUEST-ID must be unique.')

    def _log_domain(self):
        self.ensure_one()
        return ['|', ('request_id', '=', self.request_id), ('correlation_id', '=', self.request_id)]

    def _compute_log_count(self):
        Log = self.env['abdm.api.log'].sudo()
        for tx in self:
            tx.log_count = Log.search_count(tx._log_domain()) if tx.request_id else 0

    def action_view_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('API Log'),
            'res_model': 'abdm.api.log',
            'view_mode': 'list,form',
            'domain': self._log_domain(),
        }

    def action_open_related(self):
        self.ensure_one()
        if not (self.res_model and self.res_id):
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
        }

    @api.model
    def _find_by_request_id(self, request_id):
        if not request_id:
            return self.browse()
        return self.sudo().search([('request_id', '=', request_id)], limit=1)

    def _set_request(self, payload):
        self.sudo().write({'request_summary': to_log_text(payload)})

    def _set_response(self, payload, callback_path=None):
        """Store a callback answer; an ``error`` key in the body means failure."""
        error = isinstance(payload, dict) and payload.get('error')
        vals = {
            'response_date': fields.Datetime.now(),
            'response_summary': to_log_text(payload),
            'response_data': payload,
            'callback_path': callback_path,
            'state': 'error' if error else 'done',
        }
        if error:
            if isinstance(error, dict):
                vals['error_message'] = '%s %s' % (error.get('code') or '', error.get('message') or '')
            else:
                vals['error_message'] = str(error)
        self.sudo().write(vals)

    def _set_error(self, message):
        self.sudo().write({'state': 'error', 'error_message': str(message)[:5000],
                           'response_date': fields.Datetime.now()})

    @api.model
    def _cron_expire(self):
        """Mark transactions ABDM never answered, and purge old ones."""
        ICP = self.env['ir.config_parameter'].sudo()
        minutes = ICP.get_int('abdm_base.transaction_timeout_minutes', 30) or 30
        now = fields.Datetime.now()
        self.sudo().search([
            ('state', '=', 'sent'),
            ('sent_date', '<', now - timedelta(minutes=minutes)),
        ]).write({'state': 'timeout'})
        days = ICP.get_int('abdm_base.log_retention_days', 90)
        if days > 0:
            self.sudo().search([('create_date', '<', now - timedelta(days=days)),
                                ('state', '!=', 'sent')]).unlink()
