# -*- encoding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models


ACCESS_OUTCOMES = [
    ('allowed', 'Allowed'),
    ('denied', 'Denied (no permission)'),
    ('reader_denied', 'Denied (reader)'),
    ('reader_error', 'Reader error'),
    ('no_reader', 'No reader for zone'),
    ('no_zone', 'No zone for site'),
]


class EhHrAccessEvent(models.Model):
    _name = 'eh.hr.access.event'
    _description = 'Access Unlock Event'
    _order = 'created_on desc, id desc'

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    created_on = fields.Datetime(string='Recorded on', default=fields.Datetime.now, required=True, readonly=True, index=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', ondelete='set null', readonly=True, index=True)
    zone_id = fields.Many2one('eh.hr.access.zone', string='Zone', ondelete='set null', readonly=True)
    reader_id = fields.Many2one('eh.hr.access.reader', string='Reader', ondelete='set null', readonly=True)
    site_id = fields.Many2one('eh.hr.kiosk.site', string='Site', ondelete='set null', readonly=True)
    device_id = fields.Many2one('eh.hr.kiosk.terminal', string='Device', ondelete='set null', readonly=True)
    outcome = fields.Selection(ACCESS_OUTCOMES, string='Outcome', required=True, readonly=True, index=True)
    reader_response = fields.Text(string='Reader response', readonly=True)
    elapsed_ms = fields.Integer(string='Elapsed (ms)', readonly=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
        readonly=True,
    )

    @api.depends('outcome', 'employee_id', 'zone_id', 'created_on')
    def _compute_name(self):
        types = dict(self._fields['outcome'].selection)
        for record in self:
            who = record.employee_id.name or '-'
            zone = record.zone_id.name or '-'
            stamp = fields.Datetime.to_string(record.created_on) if record.created_on else ''
            record.name = ' / '.join(part for part in (types.get(record.outcome, ''), who, zone, stamp) if part)

    @api.model
    def _cron_retention_sweep(self, *, batch_limit=2000):
        now = fields.Datetime.now()
        deleted = 0
        for company in self.env['res.company'].search([]):
            horizon = company.eh_hr_access_retention_days or 365
            cutoff = now - timedelta(days=horizon)
            remaining = batch_limit - deleted
            if remaining <= 0:
                break
            stale = self.search([
                ('company_id', '=', company.id),
                ('created_on', '<=', cutoff),
            ], limit=remaining)
            if stale:
                deleted += len(stale)
                stale.unlink()
        cron_id = self.env.context.get('cron_id')
        if cron_id:
            self.env['ir.cron']._commit_progress(deleted, remaining=0)
        return deleted


class ResCompany(models.Model):
    _inherit = 'res.company'

    eh_hr_access_retention_days = fields.Integer(
        string='Access event retention (days)',
        default=365,
    )
