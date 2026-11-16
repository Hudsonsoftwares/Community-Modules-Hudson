import json
import uuid
from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, new_test_user, tagged


def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def span(start, minutes, state='active', app='Google Chrome', process='chrome.exe',
         title='Inbox', is_open=False, uid=None):
    return {'uid': uid or str(uuid.uuid4()), 'start': iso(start), 'end': iso(start + timedelta(minutes=minutes)),
            'duration': minutes * 60, 'state': state, 'app': app if state == 'active' else None,
            'process': process if state == 'active' else None,
            'title': title if state == 'active' else None, 'open': is_open}


@tagged('post_install', '-at_install')
class TestActivityMonitor(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin_user = new_test_user(cls.env, 'act_admin', groups='base.group_user,hudson_activity_monitor.group_activity_admin')
        cls.emp_user = new_test_user(cls.env, 'act_emp', groups='base.group_user')
        cls.other_user = new_test_user(cls.env, 'act_other', groups='base.group_user')
        cls.plain_user = new_test_user(cls.env, 'act_plain', groups='base.group_user')
        Employee = cls.env['hr.employee']
        cls.plain = Employee.create({'name': 'Not monitored', 'user_id': cls.plain_user.id})
        cls.employee = Employee.create({'name': 'Worker', 'user_id': cls.emp_user.id, 'tz': 'Asia/Kolkata'})
        cls.outsider = Employee.create({'name': 'Outsider', 'user_id': cls.other_user.id, 'tz': 'Asia/Kolkata'})
        # Recent fixed time so spans are "in the past" but within retention.
        cls.t0 = (datetime.utcnow() - timedelta(hours=3)).replace(second=0, microsecond=0)

    # ------------------------------------------------------------ helpers
    def _post(self, path, body, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return self.url_open(path, data=json.dumps(body), headers=headers)

    def _pair(self, employee=None, user=None):
        employee = employee or self.employee
        action = employee.with_user(user or self.admin_user).action_activity_pair_device()
        device = self.env['hr.activity.device'].browse(action['res_id'])
        resp = self._post('/api/activity/pair', {'code': device.pairing_code.replace('-', '').lower(),
                                                 'device_uid': str(uuid.uuid4()), 'hostname': 'PC-1',
                                                 'os': 'Windows-11', 'agent_version': '0.1.0'})
        self.assertEqual(resp.status_code, 200, resp.text)
        return device, resp.json()

    # -------------------------------------------------------------- tests
    def test_pairing(self):
        device, data = self._pair()
        self.assertEqual(device.state, 'paired')
        self.assertEqual(device.name, 'PC-1')
        self.assertEqual(data['employee'], 'Worker')
        self.assertTrue(data['config']['tracking_enabled'])
        self.assertTrue(self.employee.activity_monitoring_enabled)
        self.assertNotEqual(device.token_hash, data['token'], "only the hash may be stored")
        # One-time code
        resp = self._post('/api/activity/pair', {'code': 'AAAA-BBBB'})
        self.assertEqual(resp.status_code, 400)

    def test_pending_code_is_reused(self):
        first = self.employee.with_user(self.admin_user).action_activity_pair_device()['res_id']
        second = self.employee.with_user(self.admin_user).action_activity_pair_device()['res_id']
        self.assertEqual(first, second)

    def test_only_admin_can_pair(self):
        with self.assertRaises(AccessError):
            self.outsider.with_user(self.emp_user).action_activity_pair_device()
        with self.assertRaises(AccessError):
            self.env['hr.activity.device'].with_user(self.emp_user).create({'employee_id': self.outsider.id})

    def test_pairing_grants_user_role(self):
        group_user = self.env.ref('hudson_activity_monitor.group_activity_user')
        self.assertNotIn(group_user, self.emp_user.all_group_ids)
        self._pair()
        self.assertIn(group_user, self.emp_user.all_group_ids)
        self.assertNotIn(self.env.ref('hudson_activity_monitor.group_activity_admin'), self.emp_user.all_group_ids)
        # Users do not get the app menu
        root = self.env.ref('hudson_activity_monitor.menu_activity_root')
        visible = self.env['ir.ui.menu'].with_user(self.emp_user)._visible_menu_ids()
        self.assertNotIn(root.id, visible)
        self.assertIn(root.id, self.env['ir.ui.menu'].with_user(self.admin_user)._visible_menu_ids())

    def test_ingest_upsert_and_summary(self):
        device, data = self._pair()
        token = data['token']
        live_uid = str(uuid.uuid4())
        spans = [
            span(self.t0, 30),                                            # chrome 30 min
            span(self.t0 + timedelta(minutes=30), 20, app='Microsoft Excel', process='EXCEL.EXE',
                 title='Budget.xlsx'),                                    # excel 20 min
            span(self.t0 + timedelta(minutes=50), 10, state='idle'),      # idle 10 min
            span(self.t0 + timedelta(minutes=60), 5, is_open=True, uid=live_uid),
            {'uid': 'bad'},                                               # rejected
        ]
        resp = self._post('/api/activity/ingest', {'spans': spans, 'agent_version': '0.1.1'}, token)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()['accepted'], 4)
        self.assertEqual(resp.json()['rejected'], 1)

        # live span grows, then closes; an outdated open update must not reopen it
        self._post('/api/activity/ingest', {'spans': [span(self.t0 + timedelta(minutes=60), 10, uid=live_uid)]}, token)
        self._post('/api/activity/ingest', {'spans': [span(self.t0 + timedelta(minutes=60), 7, is_open=True, uid=live_uid)]}, token)
        live = self.env['hr.activity.span'].search([('uid', '=', live_uid)])
        self.assertFalse(live.is_open)
        self.assertAlmostEqual(live.duration_hours, 10 / 60, places=3)

        Span = self.env['hr.activity.span']
        self.assertEqual(Span.search_count([('employee_id', '=', self.employee.id)]), 4)
        self.assertEqual(device.agent_version, '0.1.1')
        self.assertEqual(device.status, 'active')

        daily = self.env['hr.activity.daily'].search([('employee_id', '=', self.employee.id)])
        self.assertTrue(daily)
        self.assertAlmostEqual(sum(daily.mapped('active_hours')), 60 / 60, places=3)
        self.assertAlmostEqual(sum(daily.mapped('idle_hours')), 10 / 60, places=3)
        self.assertEqual(self.env['hr.activity.app'].search([('key', '=', 'chrome.exe')]).name, 'Google Chrome')

        # Categorising an app updates productivity immediately
        excel = self.env['hr.activity.app'].search([('key', '=', 'excel.exe')])
        excel.with_user(self.admin_user).category = 'productive'
        daily.invalidate_recordset()
        self.assertAlmostEqual(sum(daily.mapped('productive_hours')), 20 / 60, places=3)

    def test_timeline_data(self):
        _device, data = self._pair()
        self._post('/api/activity/ingest', {'spans': [
            span(self.t0, 10),
            span(self.t0 + timedelta(minutes=10), 5),                                 # same app: merged
            span(self.t0 + timedelta(minutes=15), 5, app='Excel', process='excel.exe'),
            span(self.t0 + timedelta(minutes=20), 10, state='idle'),
        ]}, data['token'])
        start = fields.Datetime.to_string(self.t0 - timedelta(hours=1))
        stop = fields.Datetime.to_string(self.t0 + timedelta(hours=2))
        Span = self.env['hr.activity.span']
        res = Span.with_user(self.admin_user).get_activity_timeline([], start, stop)
        row = next(r for r in res['rows'] if r['id'] == self.employee.id)
        self.assertEqual([s['state'] for s in row['segments']], ['active', 'active', 'idle'])
        self.assertEqual(row['segments'][0]['count'], 2)
        self.assertAlmostEqual(row['active'], 20 / 60, places=3)
        self.assertEqual(row['top_apps'][0]['name'], 'Google Chrome')
        self.assertTrue(res['show_titles'])
        # merge by state (week scale) collapses the two apps into one bar
        res = Span.with_user(self.admin_user).get_activity_timeline([], start, stop, merge_by='state')
        row = next(r for r in res['rows'] if r['id'] == self.employee.id)
        self.assertEqual(len(row['segments']), 2)
        # a User only gets their own row and no titles
        res = Span.with_user(self.emp_user).get_activity_timeline([], start, stop)
        self.assertEqual([r['id'] for r in res['rows']], [self.employee.id])
        self.assertFalse(res['show_titles'])
        self.assertEqual(res['rows'][0]['segments'][0]['title'], '')

    def test_user_reads_own_reports_like_the_web_client(self):
        _device, data = self._pair()
        self._post('/api/activity/ingest', {'spans': [span(self.t0, 30)]}, data['token'])
        spec = {'date': {}, 'employee_id': {'fields': {'display_name': {}}}, 'active_hours': {},
                'top_app_id': {'fields': {'display_name': {}}}}
        Daily = self.env['hr.activity.daily'].with_user(self.emp_user)
        res = Daily.web_search_read([], spec)
        self.assertEqual(res['records'][0]['employee_id']['display_name'], 'Worker')
        Span = self.env['hr.activity.span'].with_user(self.emp_user)
        res = Span.web_search_read([], {'employee_id': {'fields': {'display_name': {}}}, 'app_id': {'fields': {'display_name': {}}},
                                        'duration_hours': {}, 'state': {}})
        self.assertEqual(res['records'][0]['employee_id']['display_name'], 'Worker')
        Span.web_read_group([], ['employee_id'], ['duration_hours:sum'])
        Daily.search([], limit=1).action_open_timeline()

    def test_revoked_token_rejected(self):
        device, data = self._pair()
        device.with_user(self.admin_user).action_revoke()
        resp = self._post('/api/activity/ingest', {'spans': []}, data['token'])
        self.assertEqual(resp.status_code, 401)
        resp = self._post('/api/activity/ingest', {'spans': []}, 'nonsense')
        self.assertEqual(resp.status_code, 401)

    def test_monitoring_disabled_pauses_agent(self):
        device, data = self._pair()
        self.employee.activity_monitoring_enabled = False
        resp = self._post('/api/activity/ingest', {'spans': []}, data['token'])
        self.assertFalse(resp.json()['config']['tracking_enabled'])

    def test_access_rights(self):
        _device, data = self._pair()
        self._post('/api/activity/ingest', {'spans': [span(self.t0, 30)]}, data['token'])
        _device2, data2 = self._pair(self.outsider, self.admin_user)
        self._post('/api/activity/ingest', {'spans': [span(self.t0, 15)]}, data2['token'])

        Span = self.env['hr.activity.span']
        Daily = self.env['hr.activity.daily']
        # employee: own only
        self.assertEqual(Span.with_user(self.emp_user).search([]).employee_id, self.employee)
        self.assertEqual(Daily.with_user(self.emp_user).search([]).employee_id, self.employee)
        # outsider sees only themself
        self.assertEqual(Span.with_user(self.other_user).search([]).employee_id, self.outsider)
        # no Activity role (never paired): no access at all
        with self.assertRaises(AccessError):
            Span.with_user(self.plain_user).search([])
        # admin: everybody
        self.assertLessEqual(self.employee | self.outsider, Span.with_user(self.admin_user).search([]).employee_id)
        # window titles: admin only (a User reading their own span cannot see it)
        rec = Span.with_user(self.emp_user).search([], limit=1)
        with self.assertRaises(AccessError):
            rec.title  # noqa: B018
        self.assertEqual(Span.with_user(self.admin_user).search([('employee_id', '=', self.employee.id)]).title, 'Inbox')
        # nobody but admins can write
        with self.assertRaises(AccessError):
            Span.with_user(self.emp_user).search([], limit=1).write({'state': 'idle'})
        # non-HR employee can still open employee records (no private-field AccessError)
        self.plain.with_user(self.emp_user).read(['name'])
        self.env['hr.employee.public'].with_user(self.emp_user).browse(self.plain.id).read(['name'])
