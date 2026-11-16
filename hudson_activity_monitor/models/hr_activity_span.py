import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from odoo import api, fields, models
from odoo.fields import Domain

_logger = logging.getLogger(__name__)

SPAN_STATES = [
    ('active', 'Active'),
    ('idle', 'Idle'),
    ('locked', 'Locked'),
]
GROUP_ADMIN = 'hudson_activity_monitor.group_activity_admin'
MAX_SPANS_PER_REQUEST = 1000
MAX_SPAN = timedelta(hours=25)
CLOCK_SKEW = timedelta(minutes=10)


def employee_zone(employee):
    try:
        return ZoneInfo(employee.tz or 'UTC')
    except Exception:  # noqa: BLE001 - invalid tz name
        return ZoneInfo('UTC')


def local_date(dt_utc, zone):
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(zone).date()


def _parse_dt(value):
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')


class HrActivitySpan(models.Model):
    _name = 'hr.activity.span'
    _description = 'Activity Span'
    _order = 'date_start desc, id desc'
    _rec_name = 'app_id'

    uid = fields.Char('Agent UID', required=True, readonly=True)
    employee_id = fields.Many2one('hr.employee', required=True, readonly=True, ondelete='cascade', index=True)
    device_id = fields.Many2one('hr.activity.device', readonly=True, ondelete='set null', index='btree_not_null')
    company_id = fields.Many2one(related='employee_id.company_id', store=True, index=True)
    department_id = fields.Many2one(related='employee_id.department_id', store=True)
    date_start = fields.Datetime('Start', required=True, readonly=True)
    date_end = fields.Datetime('End', required=True, readonly=True)
    date = fields.Date(required=True, readonly=True, index=True,
                       help="Day in the employee's time zone.")
    duration_hours = fields.Float('Duration', compute='_compute_duration', store=True, aggregator='sum')
    state = fields.Selection(SPAN_STATES, required=True, readonly=True)
    app_id = fields.Many2one('hr.activity.app', 'Application', readonly=True, index='btree_not_null')
    category = fields.Selection(related='app_id.category', store=True, string='Category')
    title = fields.Char('Window Title', readonly=True, groups=GROUP_ADMIN)
    is_open = fields.Boolean('Live', readonly=True,
                             help="Still running on the device; its end keeps moving.")

    _uid_uniq = models.Constraint('unique (uid)', 'Span UID must be unique.')
    _employee_start_idx = models.Index('(employee_id, date_start)')

    @api.depends('date_start', 'date_end')
    def _compute_duration(self):
        for span in self:
            if span.date_start and span.date_end:
                span.duration_hours = max((span.date_end - span.date_start).total_seconds(), 0) / 3600
            else:
                span.duration_hours = 0

    @api.depends('app_id', 'state')
    def _compute_display_name(self):
        labels = dict(SPAN_STATES)
        for span in self:
            span.display_name = span.app_id.name if span.state == 'active' and span.app_id else labels.get(span.state)

    # ---------------------------------------------------------------- ingest
    @api.model
    def _parse_payload(self, raw, now):
        if not isinstance(raw, dict):
            return None
        uid = raw.get('uid')
        state = raw.get('state')
        if not isinstance(uid, str) or not 8 <= len(uid) <= 64 or state not in dict(SPAN_STATES):
            return None
        try:
            start, end = _parse_dt(raw['start']), _parse_dt(raw['end'])
        except (KeyError, TypeError, ValueError):
            return None
        if end < start or end - start > MAX_SPAN or end > now + CLOCK_SKEW:
            return None

        def text(key, size):
            value = raw.get(key)
            return str(value)[:size] if value else False

        return {
            'uid': uid, 'state': state, 'date_start': start, 'date_end': end,
            'app': text('app', 128), 'process': text('process', 128),
            'title': text('title', 512), 'is_open': bool(raw.get('open')),
        }

    @api.model
    def _ingest_for_device(self, device, payload_spans):
        now = fields.Datetime.now()
        if not isinstance(payload_spans, list):
            payload_spans = []
        rejected = max(0, len(payload_spans) - MAX_SPANS_PER_REQUEST)

        parsed = {}
        for raw in payload_spans[:MAX_SPANS_PER_REQUEST]:
            vals = self._parse_payload(raw, now)
            if not vals:
                rejected += 1
                continue
            # The same uid may arrive open and closed in one batch: keep the closed one.
            if vals['uid'] not in parsed or not vals['is_open']:
                parsed[vals['uid']] = vals
        if not parsed:
            return {'accepted': 0, 'rejected': rejected, 'last_state': None}

        employee = device.employee_id
        zone = employee_zone(employee)
        Apps = self.env['hr.activity.app'].sudo()
        app_ids = Apps._get_or_create(
            (v['process'], v['app']) for v in parsed.values() if v['state'] == 'active')
        existing = {s.uid: s for s in self.search([('uid', 'in', list(parsed))])}

        to_create, touched = [], set()
        for vals in parsed.values():
            record_vals = {
                'date_start': vals['date_start'],
                'date_end': vals['date_end'],
                'date': local_date(vals['date_start'], zone),
                'state': vals['state'],
                'app_id': app_ids.get(Apps._make_key(vals['process'], vals['app']))
                if vals['state'] == 'active' else False,
                'title': vals['title'] if vals['state'] == 'active' else False,
                'is_open': vals['is_open'],
            }
            old = existing.get(vals['uid'])
            if old:
                # Never let a live (open) update overwrite a closed span, nor
                # accept a uid that belongs to someone else.
                if old.employee_id != employee or (vals['is_open'] and not old.is_open):
                    continue
                old.write(record_vals)
            else:
                to_create.append(dict(record_vals, uid=vals['uid'], employee_id=employee.id,
                                      device_id=device.id))
            touched.add(record_vals['date'])
        if to_create:
            self.create(to_create)
        self.env['hr.activity.daily'].sudo()._refresh(employee, touched)

        latest = max(parsed.values(), key=lambda v: v['date_end'])
        return {'accepted': len(parsed), 'rejected': rejected, 'last_state': latest['state']}

    # --------------------------------------------------------------- timeline
    @api.model
    def get_activity_timeline(self, domain, date_start, date_stop, merge_by='app'):
        """Data for the activity Gantt: one row per employee with merged segments.

        Runs with the caller's access rights (own data for Users, everything for
        Administrators). Consecutive spans with the same state (and application when
        merge_by == 'app') and less than a minute apart are merged to keep the DOM small.
        """
        start = fields.Datetime.to_datetime(date_start)
        stop = fields.Datetime.to_datetime(date_stop)
        dom = Domain(domain or []) & Domain([('date_start', '<', stop), ('date_end', '>', start)])
        show_titles = self.env.user.has_group(GROUP_ADMIN)
        fnames = ['employee_id', 'date_start', 'date_end', 'state', 'app_id', 'category', 'is_open']
        if show_titles:
            fnames.append('title')
        spans = self.search_fetch(dom, fnames, order='employee_id, date_start', limit=60000)
        # Names via sudo: these are employees whose activity the caller may already see.
        # Reading hr.employee as a non-HR user would fetch private (non-public) fields
        # and raise "not available for employee public profiles".
        names = {e.id: e.name for e in self.env['hr.employee'].sudo().browse(spans.employee_id.ids)}

        rows = {}
        for span in spans:
            employee_id = span.employee_id.id
            row = rows.get(employee_id)
            if row is None:
                row = rows[employee_id] = {
                    'id': employee_id, 'name': names.get(employee_id, ''), 'segments': [],
                    'active': 0.0, 'idle': 0.0, 'locked': 0.0, 'apps': {},
                }
            seg_start, seg_end = max(span.date_start, start), min(span.date_end, stop)
            hours = max((seg_end - seg_start).total_seconds(), 0) / 3600
            row[span.state] += hours
            app = span.app_id.name or ''
            if span.state == 'active' and app:
                row['apps'][app] = row['apps'].get(app, 0.0) + hours

            last = row['segments'][-1] if row['segments'] else None
            same = last and last['state'] == span.state and (merge_by == 'state' or last['app'] == app)
            if same and (seg_start - last['_end']).total_seconds() <= 60:
                last['_end'] = max(last['_end'], seg_end)
                last['hours'] += hours
                last['count'] += 1
                last['live'] = last['live'] or span.is_open
                continue
            row['segments'].append({
                'id': span.id, '_start': seg_start, '_end': seg_end, 'state': span.state,
                'app': app, 'category': span.category or '', 'hours': hours, 'count': 1,
                'title': (span.title or '') if show_titles else '', 'live': span.is_open,
            })

        result = []
        for row in sorted(rows.values(), key=lambda r: r['name'] or ''):
            for seg in row['segments']:
                seg['start'] = fields.Datetime.to_string(seg.pop('_start'))
                seg['end'] = fields.Datetime.to_string(seg.pop('_end'))
            top = sorted(row.pop('apps').items(), key=lambda kv: -kv[1])[:3]
            row['top_apps'] = [{'name': name, 'hours': hours} for name, hours in top]
            result.append(row)
        return {'rows': result, 'show_titles': show_titles}

    # ------------------------------------------------------------------ crons
    @api.model
    def _cron_maintenance(self):
        """Hourly: close live spans of devices that stopped reporting, refresh
        today's/yesterday's summaries (attendance hours change after check-out),
        and purge raw spans older than the retention period."""
        from .hr_activity_device import get_settings
        settings = get_settings(self.env)

        stale = fields.Datetime.now() - timedelta(hours=1)
        self.search([('is_open', '=', True), ('date_end', '<', stale)]).write({'is_open': False})

        today = fields.Date.context_today(self)
        recent = [today, today - timedelta(days=1)]
        rows = self._read_group([('date', 'in', recent)], ['employee_id'])
        Daily = self.env['hr.activity.daily'].sudo()
        for (employee,) in rows:
            Daily._refresh(employee, recent)

        limit = fields.Date.today() - timedelta(days=settings['retention_days'])
        while True:
            old = self.search([('date', '<', limit)], limit=10000)
            if not old:
                break
            old.unlink()
            self.env.cr.commit()
            _logger.info("Purged %s activity spans older than %s", len(old), limit)
