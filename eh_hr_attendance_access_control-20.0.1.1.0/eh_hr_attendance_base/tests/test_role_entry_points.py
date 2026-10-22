# -*- encoding: utf-8 -*-
"""The EH attendance roles, driven through the entry points a client really
uses: /web/dataset/call_kw and /web/dataset/call_button as the logged in role,
and the public kiosk routes.

Access rows and record rules guard the ORM calls they are written for. A
public method that does its work as superuser, or a secret field no group
protects, is reachable over RPC by anyone who can read the model, whatever the
view shows or hides. Each role here tries the step it must not be able to
take, and every legitimate caller (the kiosk flow, the server side API, the
manager screens, the administrator) is shown to still work.
"""
import json
import re

from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tests.common import JsonRpcException
from odoo.tools import mute_logger


ROLE_GROUPS = {
    'user': 'eh_hr_attendance_base.group_eh_hr_user',
    'auditor': 'eh_hr_attendance_base.group_eh_hr_auditor',
    'manager': 'eh_hr_attendance_base.group_eh_hr_manager',
    'admin': 'eh_hr_attendance_base.group_eh_hr_admin',
}

ACCESS_ERROR = 'odoo.exceptions.AccessError'


@tagged('post_install', '-at_install')
class TestRoleEntryPoints(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.role_users = {
            role: new_test_user(
                cls.env,
                login='eh_rpc_%s' % role,
                groups='base.group_user,%s' % group,
                company_id=cls.company.id,
            )
            for role, group in ROLE_GROUPS.items()
        }
        cls.employee_staff = cls.env['hr.employee'].create({
            'name': 'Rpc Staff',
            'company_id': cls.company.id,
            'user_id': cls.role_users['user'].id,
        })
        cls.employee_bob = cls.env['hr.employee'].create({
            'name': 'Rpc Bob',
            'company_id': cls.company.id,
        })
        cls.site = cls.env['eh.hr.kiosk.site'].create({
            'name': 'Rpc HQ',
            'code': 'rpc-hq',
            'company_id': cls.company.id,
        })
        cls.device = cls.env['eh.hr.kiosk.terminal'].create({
            'name': 'Rpc kiosk',
            'site_id': cls.site.id,
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _login(self, role):
        login = self.role_users[role].login
        self.authenticate(login, login)

    def _call_kw(self, model, method, args, kwargs=None):
        return self.make_jsonrpc_request('/web/dataset/call_kw', {
            'model': model, 'method': method, 'args': args, 'kwargs': kwargs or {},
        })

    def _call_button(self, model, method, ids):
        return self.make_jsonrpc_request('/web/dataset/call_button', {
            'model': model, 'method': method, 'args': [ids], 'kwargs': {},
        })

    def _assert_refused(self, call, *args, msg=None):
        with self.assertRaises(JsonRpcException, msg=msg) as caught:
            call(*args)
        self.assertEqual(caught.exception.args[0], ACCESS_ERROR, msg)

    def _pair(self, pin, device_name):
        return self.url_open(
            '/eh_hr/kiosk/pair',
            data=json.dumps({'site_code': self.site.code, 'pin': pin, 'device_name': device_name}),
            headers={'Content-Type': 'application/json'},
        )

    def _heartbeat(self, token):
        return self.url_open(
            '/eh_hr/kiosk/heartbeat',
            data='{}',
            headers={'Content-Type': 'application/json', 'X-EH-Kiosk-Token': token},
        )

    # ------------------------------------------------------------------
    # Registering a kiosk: the pairing PIN
    # ------------------------------------------------------------------
    @mute_logger('odoo.http')
    def test_only_an_admin_issues_a_pairing_pin(self):
        """The PIN is what a kiosk trades for a device token, so issuing one
        registers a device. Every role below Admin reads the site, and the
        button alone used to be the only thing in the way."""
        Terminal = self.env['eh.hr.kiosk.terminal'].with_context(active_test=False)
        before = Terminal.search([])
        for role in ('user', 'auditor', 'manager'):
            self._login(role)
            self._assert_refused(
                self._call_button, 'eh.hr.kiosk.site', 'action_issue_pairing_pin', self.site.ids,
                msg=role)
        self.assertEqual(Terminal.search([]), before)

        # The administrator issues the PIN from the site form and the kiosk
        # trades it for a device token, which lands in the audit log.
        self._login('admin')
        action = self._call_button('eh.hr.kiosk.site', 'action_issue_pairing_pin', self.site.ids)
        pin = re.search(r': (\d{6})\.', action['params']['message']).group(1)
        response = self._pair(pin, 'Admin paired kiosk')
        self.assertEqual(response.status_code, 200)
        paired = Terminal.search([('name', '=', 'Admin paired kiosk')])
        self.assertEqual(paired.site_id, self.site)
        self.assertEqual(response.json()['device_token'], paired.device_token)
        self.assertTrue(self.env['eh.hr.kiosk.event'].search([
            ('event_type', '=', 'device_register'), ('device_id', '=', paired.id)]))
        # One shot: the same PIN does not pair a second device.
        self.assertEqual(self._pair(pin, 'Replayed kiosk').status_code, 403)

    # ------------------------------------------------------------------
    # The audit log
    # ------------------------------------------------------------------
    @mute_logger('odoo.http')
    def test_no_role_writes_the_audit_log_over_rpc(self):
        """No role has create on the audit log; its server side API used to
        be a public method that created as superuser, so the read only
        auditor could forge events. It is for server code only now."""
        Event = self.env['eh.hr.kiosk.event']
        for role in ROLE_GROUPS:
            self._login(role)
            self._assert_refused(
                self._call_kw, 'eh.hr.kiosk.event', 'log', ['match_success'],
                {'employee_id': self.employee_bob.id, 'notes': 'forged by %s' % role},
                msg=role)
            self._assert_refused(
                self._call_kw, 'eh.hr.kiosk.event', 'create',
                [{'event_type': 'match_success', 'notes': 'created by %s' % role}],
                msg=role)
        self.assertFalse(Event.search(['|', ('notes', '=like', 'forged by %'), ('notes', '=like', 'created by %')]))

        # The kiosk flow still writes it: a paired device's heartbeat is
        # logged by the route.
        response = self._heartbeat(self.device.device_token)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Event.search([
            ('event_type', '=', 'device_heartbeat'), ('device_id', '=', self.device.id)]))
        # And so does server code calling the API in process.
        event = Event.log('error', device_id=self.device.id, notes='Logged by server code')
        self.assertEqual(event.site_id, self.site)
        # The roles that read the log still do.
        self._login('auditor')
        rows = self._call_kw('eh.hr.kiosk.event', 'search_read', [[['id', '=', event.id]]], {'fields': ['notes']})
        self.assertEqual(rows[0]['notes'], 'Logged by server code')

    # ------------------------------------------------------------------
    # Attendance exceptions
    # ------------------------------------------------------------------
    @mute_logger('odoo.http')
    def test_no_role_raises_an_exception_over_rpc(self):
        """The server side API created the exception as superuser for any
        employee, so a staff member could raise one on any colleague. It is
        for server code only now; managers file exceptions through the
        form, under their own access rights."""
        Exception_ = self.env['eh.hr.attendance.exception']
        for role in ROLE_GROUPS:
            self._login(role)
            self._assert_refused(
                self._call_kw, 'eh.hr.attendance.exception', 'raise_exception',
                [self.employee_bob.id, 'no_show'],
                {'severity': 'critical', 'description': 'raised by %s' % role},
                msg=role)
        for role in ('user', 'auditor'):
            self._login(role)
            self._assert_refused(
                self._call_kw, 'eh.hr.attendance.exception', 'create',
                [{'employee_id': self.employee_bob.id, 'exception_type': 'no_show',
                  'description': 'created by %s' % role}],
                msg=role)
        self.assertFalse(Exception_.search([('employee_id', '=', self.employee_bob.id)]))

        # A manager files and resolves one from the screens.
        self._login('manager')
        exception_id = self._call_kw('eh.hr.attendance.exception', 'create', [{
            'employee_id': self.employee_bob.id,
            'exception_type': 'manual',
            'description': 'Filed by the manager',
        }])
        self._call_button('eh.hr.attendance.exception', 'action_resolve', [exception_id])
        filed = Exception_.browse(exception_id)
        self.assertTrue(filed.resolved)
        self.assertEqual(filed.resolved_by, self.role_users['manager'])

        # Server code (the kiosk and mobile routes) still raises them, with
        # the audit event.
        raised = Exception_.raise_exception(
            employee=self.employee_bob, exception_type='identity_low_confidence',
            description='Raised by server code')
        self.assertEqual(raised.employee_id, self.employee_bob)
        self.assertTrue(self.env['eh.hr.kiosk.event'].search([
            ('event_type', '=', 'exception_raised'),
            ('ref_model', '=', 'eh.hr.attendance.exception'),
            ('ref_id', '=', raised.id)]))

    # ------------------------------------------------------------------
    # Device tokens
    # ------------------------------------------------------------------
    @mute_logger('odoo.http')
    def test_only_an_admin_reads_a_device_token(self):
        """A device token is the kiosk's credential: whoever holds it can
        post attendance through the kiosk routes. The auditor and the
        manager read the terminal registry, never the token."""
        token = self.device.device_token
        domain = [['id', '=', self.device.id]]
        for role in ('auditor', 'manager'):
            self._login(role)
            self._assert_refused(
                self._call_kw, 'eh.hr.kiosk.terminal', 'search_read', [domain], {'fields': ['device_token']},
                msg=role)
            self._assert_refused(
                self._call_kw, 'eh.hr.kiosk.terminal', 'web_read', [self.device.ids],
                {'specification': {'device_token': {}}},
                msg=role)
            # Nor can it be guessed a character at a time through a search.
            self._assert_refused(
                self._call_kw, 'eh.hr.kiosk.terminal', 'search_count',
                [[['device_token', '=like', token[:1] + '%']]],
                msg=role)
            # The registry itself stays readable: every other field, the
            # fields the client is told about, and the screens.
            rows = self._call_kw('eh.hr.kiosk.terminal', 'search_read', [domain], {})
            self.assertEqual(rows[0]['name'], 'Rpc kiosk', role)
            self.assertNotIn('device_token', rows[0], role)
            fields = self._call_kw('eh.hr.kiosk.terminal', 'fields_get', [], {'attributes': ['type']})
            self.assertNotIn('device_token', fields, role)
            views = self._call_kw('eh.hr.kiosk.terminal', 'get_views', [], {
                'views': [[False, 'list'], [False, 'form']]})['views']
            self.assertNotIn('device_token', views['form']['arch'], role)
            self._call_kw('eh.hr.kiosk.terminal', 'web_read', [self.device.ids], {
                'specification': {'name': {}, 'site_id': {'fields': {'display_name': {}}},
                                  'registered_on': {}, 'last_seen': {}, 'last_ip': {}, 'user_agent': {}}})
        # A manager cannot rotate it either: rotating is writing it.
        self._assert_refused(
            self._call_button, 'eh.hr.kiosk.terminal', 'action_rotate_token', self.device.ids)
        self.device.invalidate_recordset()
        self.assertEqual(self.device.device_token, token)

        # The administrator reads and rotates it, and the kiosk routes take
        # the new token only.
        self._login('admin')
        rows = self._call_kw('eh.hr.kiosk.terminal', 'search_read', [domain], {'fields': ['device_token']})
        self.assertEqual(rows[0]['device_token'], token)
        self._call_button('eh.hr.kiosk.terminal', 'action_rotate_token', self.device.ids)
        self.device.invalidate_recordset()
        self.assertNotEqual(self.device.device_token, token)
        self.assertEqual(self._heartbeat(token).status_code, 401)
        self.assertEqual(self._heartbeat(self.device.device_token).status_code, 200)
