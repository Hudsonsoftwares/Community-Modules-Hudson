from collections import defaultdict
from datetime import date as date_cls, datetime, time, timedelta, timezone

from odoo import _, api, fields, models

from .hr_activity_span import employee_zone


class HrActivityDaily(models.Model):
    _name = 'hr.activity.daily'
    _description = 'Daily Activity Summary'
    _order = 'date desc, employee_id'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one('hr.employee', required=True, readonly=True, ondelete='cascade', index=True)
    date = fields.Date(required=True, readonly=True, index=True)
    company_id = fields.Many2one(related='employee_id.company_id', store=True, index=True)
    department_id = fields.Many2one(related='employee_id.department_id', store=True)
    active_hours = fields.Float('Active', readonly=True, aggregator='sum')
    idle_hours = fields.Float('Idle', readonly=True, aggregator='sum')
    locked_hours = fields.Float('Locked / Away', readonly=True, aggregator='sum')
    productive_hours = fields.Float('Productive', readonly=True, aggregator='sum')
    neutral_hours = fields.Float('Neutral', readonly=True, aggregator='sum')
    unproductive_hours = fields.Float('Unproductive', readonly=True, aggregator='sum')
    attendance_hours = fields.Float('Attendance', readonly=True, aggregator='sum',
                                    help="Worked hours from check-in / check-out on this day.")
    activity_pct = fields.Float('Activity %', readonly=True, aggregator='avg',
                                help="Active time / (active + idle) time.")
    productivity_pct = fields.Float('Productivity %', readonly=True, aggregator='avg',
                                    help="Productive time / active time.")
    first_seen = fields.Datetime(readonly=True)
    last_seen = fields.Datetime(readonly=True)
    top_app_id = fields.Many2one('hr.activity.app', 'Top Application', readonly=True)

    _employee_date_uniq = models.Constraint('unique (employee_id, date)',
                                            'One summary per employee and day.')

    def action_open_timeline(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'hudson_activity_monitor.action_hr_activity_span_timeline')
        action['domain'] = [('employee_id', '=', self.employee_id.id), ('date', '=', self.date)]
        action['context'] = {'initial_date': fields.Date.to_string(self.date)}
        action['display_name'] = _("%(employee)s - %(date)s", employee=self.employee_id.sudo().name, date=self.date)
        return action

    # --------------------------------------------------------------- refresh
    @api.model
    def _refresh(self, employees, dates):
        """Recompute the summaries of the given employees for the given days."""
        dates = sorted({d for d in dates if d})
        if not employees or not dates:
            return
        Span = self.env['hr.activity.span'].sudo()
        domain = [('employee_id', 'in', employees.ids), ('date', 'in', dates)]
        data = defaultdict(lambda: defaultdict(float))

        groups = Span._read_group(
            domain, ['employee_id', 'date:day', 'state', 'category'],
            ['duration_hours:sum', 'date_start:min', 'date_end:max'])
        for employee, day, state, category, hours, first, last in groups:
            row = data[(employee.id, day)]
            row[f'{state}_hours'] += hours
            if state == 'active':
                row[f'{category or "neutral"}_hours'] += hours
            row['first_seen'] = min(filter(None, [row.get('first_seen'), first]))
            row['last_seen'] = max(filter(None, [row.get('last_seen'), last]))

        top = {}
        for employee, day, app, hours in Span._read_group(
                domain + [('state', '=', 'active'), ('app_id', '!=', False)],
                ['employee_id', 'date:day', 'app_id'], ['duration_hours:sum']):
            if hours > top.get((employee.id, day), (None, -1))[1]:
                top[(employee.id, day)] = (app.id, hours)

        attendance = self._attendance_hours(employees, dates)

        existing = {(r.employee_id.id, r.date): r for r in self.search(domain)}
        to_create = []
        for key in set(data) | set(existing):
            row = data.get(key, {})
            active, idle = row.get('active_hours', 0.0), row.get('idle_hours', 0.0)
            vals = {
                'active_hours': active,
                'idle_hours': idle,
                'locked_hours': row.get('locked_hours', 0.0),
                'productive_hours': row.get('productive_hours', 0.0),
                'neutral_hours': row.get('neutral_hours', 0.0),
                'unproductive_hours': row.get('unproductive_hours', 0.0),
                'activity_pct': 100 * active / (active + idle) if active + idle else 0.0,
                'productivity_pct': 100 * row.get('productive_hours', 0.0) / active if active else 0.0,
                'first_seen': row.get('first_seen') or False,
                'last_seen': row.get('last_seen') or False,
                'top_app_id': top.get(key, (False,))[0],
                'attendance_hours': attendance.get(key, 0.0),
            }
            if key in existing:
                existing[key].write(vals)
            else:
                to_create.append(dict(vals, employee_id=key[0], date=key[1]))
        if to_create:
            self.create(to_create)

    @api.model
    def _attendance_hours(self, employees, dates):
        """{(employee_id, date): worked hours} using each employee's time zone."""
        result = defaultdict(float)
        Attendance = self.env['hr.attendance'].sudo()
        first, last = min(dates), max(dates) + timedelta(days=1)
        for employee in employees:
            zone = employee_zone(employee)
            lo = datetime.combine(first, time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
            hi = datetime.combine(last, time.min, zone).astimezone(timezone.utc).replace(tzinfo=None)
            for att in Attendance.search_fetch(
                    [('employee_id', '=', employee.id), ('check_in', '>=', lo), ('check_in', '<', hi)],
                    ['check_in', 'worked_hours']):
                day = att.check_in.replace(tzinfo=timezone.utc).astimezone(zone).date()
                result[(employee.id, day)] += att.worked_hours
        return result

    @api.model
    def _refresh_for_apps(self, apps):
        """After an application's category changes, refresh the last 31 days."""
        since = date_cls.today() - timedelta(days=31)
        Span = self.env['hr.activity.span'].sudo()
        rows = Span._read_group([('app_id', 'in', apps.ids), ('date', '>=', since)],
                                ['employee_id'], ['date:array_agg'])
        for employee, days in rows:
            self._refresh(employee, set(days))

    @api.model
    def action_refresh_all(self):
        """Server action: rebuild the last 31 days for everybody."""
        since = date_cls.today() - timedelta(days=31)
        Span = self.env['hr.activity.span'].sudo()
        for employee, days in Span._read_group([('date', '>=', since)], ['employee_id'], ['date:array_agg']):
            self.sudo()._refresh(employee, set(days))
