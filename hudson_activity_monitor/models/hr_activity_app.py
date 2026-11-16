import logging

from psycopg2 import IntegrityError

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

CATEGORIES = [
    ('productive', 'Productive'),
    ('neutral', 'Neutral'),
    ('unproductive', 'Unproductive'),
]


class HrActivityApp(models.Model):
    _name = 'hr.activity.app'
    _description = 'Tracked Application'
    _order = 'name'

    name = fields.Char('Application', required=True)
    process = fields.Char('Process / Bundle ID', readonly=True,
                          help="Executable name on Windows (chrome.exe) or bundle id on macOS.")
    key = fields.Char(required=True, index=True, readonly=True)
    category = fields.Selection(CATEGORIES, default='neutral', required=True)
    color = fields.Integer()
    active = fields.Boolean(default=True)

    _key_uniq = models.Constraint('unique (key)', 'This application already exists.')

    @staticmethod
    def _make_key(process, name):
        return (process or name or 'unknown').strip().lower()[:128]

    @api.model
    def _get_or_create(self, pairs):
        """pairs: iterable of (process, name). Returns {key: app_id}."""
        wanted = {}
        for process, name in pairs:
            wanted.setdefault(self._make_key(process, name), (process, name))
        if not wanted:
            return {}
        apps = self.with_context(active_test=False).search_fetch([('key', 'in', list(wanted))], ['key'])
        result = {app.key: app.id for app in apps}
        for key, (process, name) in wanted.items():
            if key in result:
                continue
            try:
                with self.env.cr.savepoint():
                    app = self.create({'key': key, 'process': process, 'name': name or process or 'Unknown',
                                       'color': len(result) % 11 + 1})
            except IntegrityError:
                # Created concurrently by another request.
                app = self.with_context(active_test=False).search([('key', '=', key)], limit=1)
            result[key] = app.id
        return result

    def write(self, vals):
        res = super().write(vals)
        if 'category' in vals:
            self.env['hr.activity.daily'].sudo()._refresh_for_apps(self)
        return res
