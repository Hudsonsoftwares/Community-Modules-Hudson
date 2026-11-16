# Part of Hudson Community. See LICENSE file for full copyright and licensing details.
"""Gateway clients: other Odoo databases that use this database's AI key with their own limits."""

import hashlib
import secrets
from datetime import datetime, time

from odoo import _, api, fields, models

KEY_PREFIX = 'hai_'


def _hash_key(key):
    # Keys are long random tokens: a plain SHA-256 is enough and allows an indexed lookup.
    return hashlib.sha256(key.encode()).hexdigest()


class HudsonAIClient(models.Model):
    _name = 'hudson.ai.client'
    _description = 'Hudson AI Gateway Client'
    _order = 'name'

    name = fields.Char(required=True)
    partner_id = fields.Many2one('res.partner', string='Customer')
    active = fields.Boolean(default=True)
    key_hash = fields.Char(readonly=True, copy=False, index=True, groups='base.group_system')
    key_hint = fields.Char(string='Key', readonly=True, copy=False,
                           help='Start of the key, to recognise it. The full key is shown only once.')
    monthly_token_limit = fields.Integer(
        string='Tokens / Month', default=1_000_000,
        help='Total tokens (question + answer) the client may use per calendar month. 0 = unlimited.')
    daily_request_limit = fields.Integer(
        string='API Calls / Day', default=500,
        help='Calls to the AI per day. One question can take several calls when the AI looks up '
             'data. 0 = unlimited.')
    tokens_this_month = fields.Integer(compute='_compute_usage')
    requests_today = fields.Integer(string='Calls Today', compute='_compute_usage')
    token_usage_percent = fields.Float(string='Monthly Usage', compute='_compute_usage')
    last_used = fields.Datetime(compute='_compute_usage')
    usage_ids = fields.One2many('hudson.ai.usage', 'client_id')
    note = fields.Text()

    _key_hash_uniq = models.Constraint('unique(key_hash)', 'This key is already used.')
    _limits_positive = models.Constraint(
        'CHECK(monthly_token_limit >= 0 AND daily_request_limit >= 0)', 'Limits cannot be negative.')

    @api.model
    def _period_starts(self):
        now = fields.Datetime.now()
        return datetime.combine(now.date().replace(day=1), time.min), datetime.combine(now.date(), time.min)

    def _compute_usage(self):
        month_start, day_start = self._period_starts()
        Usage = self.env['hudson.ai.usage'].sudo()
        month = {client.id: (tokens, last) for client, tokens, last in Usage._read_group(
            [('client_id', 'in', self.ids), ('date', '>=', month_start)],
            ['client_id'], ['total_tokens:sum', 'date:max'])}
        today = {client.id: count for client, count in Usage._read_group(
            [('client_id', 'in', self.ids), ('date', '>=', day_start)], ['client_id'], ['__count'])}
        for client in self:
            tokens, last = month.get(client.id, (0, False))
            client.tokens_this_month = tokens
            client.requests_today = today.get(client.id, 0)
            client.token_usage_percent = (
                100.0 * tokens / client.monthly_token_limit if client.monthly_token_limit else 0.0)
            client.last_used = last

    # ------------------------------------------------------------------ keys

    def action_generate_key(self):
        """Create a new key (the old one stops working) and show it once."""
        self.ensure_one()
        key = KEY_PREFIX + secrets.token_urlsafe(32)
        self.sudo().write({'key_hash': _hash_key(key), 'key_hint': key[:10] + '…'})
        wizard = self.env['hudson.ai.client.key'].create({'client_id': self.id, 'key': key})
        return {
            'type': 'ir.actions.act_window',
            'name': _('API key for %s', self.name),
            'res_model': 'hudson.ai.client.key',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_revoke_key(self):
        self.sudo().write({'key_hash': False, 'key_hint': False})

    def action_view_usage(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Usage of %s', self.name),
            'res_model': 'hudson.ai.usage',
            'view_mode': 'list,pivot,graph',
            'domain': [('client_id', '=', self.id)],
            'context': {'search_default_this_month': 1},
        }

    @api.model
    def _authenticate(self, key):
        if not key or not key.startswith(KEY_PREFIX):
            return self.browse()
        return self.sudo().search([('key_hash', '=', _hash_key(key))], limit=1)

    def _quota_error(self):
        """Return a message when the client may not make another call, else None."""
        self.ensure_one()
        if self.daily_request_limit and self.requests_today >= self.daily_request_limit:
            return _('Daily AI limit reached (%(used)s of %(limit)s calls). It resets at midnight UTC.',
                     used=self.requests_today, limit=self.daily_request_limit)
        if self.monthly_token_limit and self.tokens_this_month >= self.monthly_token_limit:
            return _('Monthly AI credits used up (%(used)s of %(limit)s tokens). They reset on the 1st.',
                     used=f'{self.tokens_this_month:,}', limit=f'{self.monthly_token_limit:,}')
        return None

    def _usage_summary(self):
        self.ensure_one()
        return {
            'client': self.name,
            'tokens_this_month': self.tokens_this_month,
            'monthly_token_limit': self.monthly_token_limit,
            'requests_today': self.requests_today,
            'daily_request_limit': self.daily_request_limit,
        }


class HudsonAIClientKey(models.TransientModel):
    _name = 'hudson.ai.client.key'
    _description = 'Show a newly generated gateway key once'

    client_id = fields.Many2one('hudson.ai.client', required=True, readonly=True)
    key = fields.Char(readonly=True)
    gateway_url = fields.Char(compute='_compute_gateway_url')
    database = fields.Char(compute='_compute_gateway_url')

    def _compute_gateway_url(self):
        base = self.env['ir.config_parameter'].sudo().get_str('web.base.url')
        for wizard in self:
            wizard.gateway_url = f'{base}/hudson_ai/v1'
            wizard.database = self.env.cr.dbname

    def action_done(self):
        # Do not keep the plain key in the database (transient records are
        # vacuumed anyway, but there is no reason to wait).
        self.unlink()
        return {'type': 'ir.actions.act_window_close'}
