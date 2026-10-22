# -*- encoding: utf-8 -*-
"""Who reads a door permission, driven through the entry points a client
really uses: /web/dataset/call_kw as the logged in role, and the kiosk unlock
route.

A permission row says which doors an employee may open and until when. The
EH Attendance User is staff: they may read their own rows, never a
colleague's. Granting doors is the attendance manager's work, the auditor
reads the whole register, and the kiosk checks permissions as superuser once
its device token is known, so none of that depends on what staff can read.
"""
import json
from unittest.mock import patch

from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tests.common import JsonRpcException
from odoo.tools import mute_logger


ROLE_GROUPS = {
    'staff': 'eh_hr_attendance_base.group_eh_hr_user',
    'manager': 'eh_hr_attendance_base.group_eh_hr_manager',
    'auditor': 'eh_hr_attendance_base.group_eh_hr_auditor',
    # An HR Officer who also clocks in: the 20.0.1.1.0 upgrade of the base
    # module gives HR Officer explicitly to every former EH User.
    'hr_staff': 'hr.group_hr_user,eh_hr_attendance_base.group_eh_hr_user',
}

ACCESS_ERROR = 'odoo.exceptions.AccessError'


@tagged('post_install', '-at_install')
class TestAccessPermissionRoles(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.role_users = {
            role: new_test_user(
                cls.env,
                login='eh_door_role_%s' % role,
                groups='base.group_user,%s' % groups,
                company_id=cls.company.id,
            )
            for role, groups in ROLE_GROUPS.items()
        }
        Employee = cls.env['hr.employee']
        cls.staff = Employee.create({
            'name': 'Door Role Staff',
            'company_id': cls.company.id,
            'user_id': cls.role_users['staff'].id,
        })
        cls.carol = Employee.create({
            'name': 'Door Role Carol',
            'company_id': cls.company.id,
        })
        cls.site = cls.env['eh.hr.kiosk.site'].create({
            'name': 'Door role site',
            'code': 'door-role',
            'company_id': cls.company.id,
        })
        cls.device = cls.env['eh.hr.kiosk.terminal'].create({
            'name': 'Door role kiosk',
            'site_id': cls.site.id,
        })
        cls.zone = cls.env['eh.hr.access.zone'].create({
            'name': 'Door role zone',
            'code': 'door-role-zone',
            'site_ids': [(6, 0, cls.site.ids)],
            'company_id': cls.company.id,
        })
        cls.reader = cls.env['eh.hr.access.reader'].create({
            'name': 'Door role relay',
            'zone_id': cls.zone.id,
            'webhook_url': 'http://localhost:9999/unlock',
        })
        Permission = cls.env['eh.hr.access.permission']
        cls.staff_permission = Permission.create({
            'employee_id': cls.staff.id,
            'zone_id': cls.zone.id,
        })
        cls.carol_permission = Permission.create({
            'employee_id': cls.carol.id,
            'zone_id': cls.zone.id,
        })

    def _login(self, role):
        login = self.role_users[role].login
        self.authenticate(login, login)

    def _call_kw(self, model, method, args, kwargs=None):
        return self.make_jsonrpc_request('/web/dataset/call_kw', {
            'model': model, 'method': method, 'args': args, 'kwargs': kwargs or {},
        })

    def _visible(self):
        rows = self._call_kw(
            'eh.hr.access.permission', 'search_read', [[]], {'fields': ['id']})
        return {row['id'] for row in rows}

    def _assert_refused(self, call, *args, msg=None):
        with self.assertRaises(JsonRpcException, msg=msg) as caught:
            call(*args)
        self.assertEqual(caught.exception.args[0], ACCESS_ERROR, msg)

    def _employee_form_arch(self):
        views = self._call_kw('hr.employee', 'get_views', [], {
            'views': [[False, 'form']]})
        return views['views']['form']['arch']

    @mute_logger('odoo.http')
    def test_staff_reads_only_their_own_door_permissions(self):
        self._login('staff')
        visible = self._visible()
        self.assertIn(self.staff_permission.id, visible)
        self.assertNotIn(self.carol_permission.id, visible)
        self._assert_refused(
            self._call_kw, 'eh.hr.access.permission', 'web_read',
            [self.carol_permission.ids],
            {'specification': {'zone_id': {'fields': {'display_name': {}}}, 'valid_to': {}}})
        count = self._call_kw('eh.hr.access.permission', 'search_count', [[
            ('zone_id', '=', self.zone.id)]])
        self.assertEqual(count, 1)

    def test_manager_and_auditor_read_every_door_permission(self):
        for role in ('manager', 'auditor'):
            self._login(role)
            visible = self._visible()
            self.assertIn(self.staff_permission.id, visible, role)
            self.assertIn(self.carol_permission.id, visible, role)

    def test_the_employee_form_lists_doors_only_to_those_who_read_them_all(self):
        """The door list on the employee form shows every permission of that
        employee, so it is for the roles that read them all. An HR Officer who
        is only staff here would otherwise see a colleague's doors as an empty
        list."""
        self._login('hr_staff')
        self.assertNotIn('eh_access_permission_ids', self._employee_form_arch())
        [row] = self._call_kw('hr.employee', 'web_read', [self.carol.ids], {
            'specification': {'name': {}}})
        self.assertEqual(row['name'], 'Door Role Carol')

        self._login('manager')
        self.assertIn('eh_access_permission_ids', self._employee_form_arch())
        [row] = self._call_kw('hr.employee', 'web_read', [self.carol.ids], {
            'specification': {'eh_access_permission_ids': {'fields': {'zone_id': {}}}}})
        self.assertEqual(
            [line['id'] for line in row['eh_access_permission_ids']],
            self.carol_permission.ids)

    def test_the_kiosk_still_opens_the_door_for_a_permitted_employee(self):
        class MockResp:
            status_code = 200
            text = 'ok'

        with patch('requests.post', return_value=MockResp()):
            response = self.url_open(
                '/eh_hr/kiosk/access/trigger',
                data=json.dumps({'employee_id': self.staff.id}),
                headers={
                    'Content-Type': 'application/json',
                    'X-EH-Kiosk-Token': self.device.device_token,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['outcome'], 'allowed')
