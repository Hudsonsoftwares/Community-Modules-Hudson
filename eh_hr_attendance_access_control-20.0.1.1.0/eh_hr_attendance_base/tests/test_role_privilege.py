# -*- encoding: utf-8 -*-
"""Least privilege for the EH Attendance User and Auditor roles.

Both roles used to imply hr.group_hr_user. On Odoo 20 that group is the only
one outside the administrators with any right on hr.employee, and the right is
create, write and delete on every employee and their private data. A staff
member given the role meant for their own attendance became an HR Officer
over everyone, and the auditor labelled read only could rewrite employees.

Each role now holds exactly what its own screens and flows need, proven here
on the models and on the screens themselves: the menus of this suite a role
can reach are opened the way the web client opens them (views, list read,
form read, every group by of the search view), so a right that went missing
with the implication shows up as an error rather than as a blank screen.
"""
from datetime import datetime

from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval

from .common import EhHrTestCommon


ROLE_GROUPS = {
    'user': 'eh_hr_attendance_base.group_eh_hr_user',
    'auditor': 'eh_hr_attendance_base.group_eh_hr_auditor',
    'manager': 'eh_hr_attendance_base.group_eh_hr_manager',
    'admin': 'eh_hr_attendance_base.group_eh_hr_admin',
}

# What each role may do on the model, whatever the record. 'c' create, 'r'
# read, 'u' write, 'd' unlink. The user's hr.attendance rights are the
# standard Self Attendance Edit role (own rows only, see the record tests);
# the auditor reads their own attendance like every internal user. Neither
# has any right on hr.employee: other employees are read through the public
# employee profile.
MODEL_MATRIX = {
    'hr.employee': {'user': '', 'auditor': '', 'manager': 'crud', 'admin': 'crud'},
    'hr.attendance': {'user': 'cru', 'auditor': 'r'},
    'eh.hr.consent': {'user': 'r', 'auditor': 'r', 'manager': 'cru', 'admin': 'crud'},
    'eh.hr.kiosk.site': {'user': 'r', 'auditor': 'r', 'manager': 'cru', 'admin': 'crud'},
    # Renaming, moving and revoking a terminal is Admin configuration.
    'eh.hr.kiosk.terminal': {'user': '', 'auditor': 'r', 'manager': 'r', 'admin': 'crud'},
    'eh.hr.kiosk.event': {'user': '', 'auditor': 'r', 'manager': 'r', 'admin': 'rd'},
    'eh.hr.attendance.exception': {'user': 'r', 'auditor': 'r', 'manager': 'cru', 'admin': 'crud'},
}

OPERATIONS = {'c': 'create', 'r': 'read', 'u': 'write', 'd': 'unlink'}

# The screens of this suite a role reaches from the People Operations menu.
SUITE_MODULES = ('eh_hr_attendance_base', 'eh_hr_face_kiosk')


class TestRolePrivilege(EhHrTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_users = {
            role: new_test_user(
                cls.env,
                login='eh_least_%s' % role,
                groups='base.group_user,%s' % group,
                company_id=cls.company.id,
            )
            for role, group in ROLE_GROUPS.items()
        }
        cls.user = cls.role_users['user']
        cls.auditor = cls.role_users['auditor']
        cls.employee_alice.user_id = cls.user
        cls.employee_auditor = cls.Employee.create({
            'name': 'Auditor Test',
            'company_id': cls.company.id,
            'user_id': cls.auditor.id,
        })
        cls.alice_consent = cls.Consent.create({
            'employee_id': cls.employee_alice.id,
            'consent_type': 'face',
            'company_id': cls.company.id,
        })
        cls.alice_consent.action_grant()
        cls.bob_consent = cls.Consent.create({
            'employee_id': cls.employee_bob.id,
            'consent_type': 'geolocation',
            'company_id': cls.company.id,
        })
        cls.bob_consent.action_grant()
        cls.alice_exception = cls.Exception_.raise_exception(
            employee=cls.employee_alice, exception_type='late')
        cls.bob_exception = cls.Exception_.raise_exception(
            employee=cls.employee_bob, exception_type='no_show')
        cls.event = cls.Event.log(
            'match_fail', employee_id=cls.employee_bob.id,
            device_id=cls.device.id, company_id=cls.company.id)
        cls.bob_attendance = cls.env['hr.attendance'].create({
            'employee_id': cls.employee_bob.id,
            'check_in': datetime(2026, 5, 4, 9),
            'check_out': datetime(2026, 5, 4, 17),
        })

    def _as(self, user, records):
        # A fresh cache, so nothing the setup read as administrator can stand
        # in for a read the role is not allowed to make.
        self.env.flush_all()
        self.env.invalidate_all()
        return records.with_user(user)

    # ------------------------------------------------------------------
    # The roles themselves
    # ------------------------------------------------------------------
    def test_user_and_auditor_do_not_imply_hr_officer(self):
        officer = self.env.ref('hr.group_hr_user')
        for role in ('user', 'auditor'):
            group = self.env.ref(ROLE_GROUPS[role])
            self.assertNotIn(officer, group.all_implied_ids, role)
            self.assertFalse(self.role_users[role].has_group('hr.group_hr_user'), role)
        # The user role carries the standard own attendance role, nothing more
        # of HR; the auditor only the internal user role. Odoo itself adds the
        # regular user marker to every group that is not a light one.
        regular = self.env.ref('base.group_user_regular')
        self.assertEqual(
            self.env.ref(ROLE_GROUPS['user']).implied_ids - regular,
            self.env.ref('hr_attendance.group_hr_attendance_own'))
        self.assertEqual(
            self.env.ref(ROLE_GROUPS['auditor']).implied_ids - regular,
            self.env.ref('base.group_user'))

    def test_manager_and_admin_keep_hr_administrator(self):
        for role in ('manager', 'admin'):
            self.assertTrue(self.role_users[role].has_group('hr.group_hr_manager'), role)
            self.assertTrue(self.role_users[role].has_group(ROLE_GROUPS['user']), role)

    def test_model_access_matrix(self):
        for model, per_role in MODEL_MATRIX.items():
            for role, allowed in per_role.items():
                empty = self.env[model].with_user(self.role_users[role]).browse()
                for letter, operation in OPERATIONS.items():
                    self.assertEqual(
                        empty.has_access(operation), letter in allowed,
                        'role %s on %s: unexpected %s access' % (role, model, operation))

    # ------------------------------------------------------------------
    # EH Attendance User: own rows only
    # ------------------------------------------------------------------
    def test_user_cannot_change_any_employee(self):
        for employee in (self.employee_bob, self.employee_alice):
            as_user = self._as(self.user, employee)
            for operation in ('write', 'unlink'):
                self.assertFalse(as_user.has_access(operation), operation)
            with self.assertRaises(AccessError):
                as_user.write({'private_street': 'Changed by a staff member'})
            with self.assertRaises(AccessError):
                as_user.unlink()
        with self.assertRaises(AccessError):
            self.Employee.with_user(self.user).create({'name': 'Created by a staff member'})
        self.assertFalse(self.employee_bob.private_street)

    def test_user_reads_colleagues_through_the_public_profile_only(self):
        bob = self._as(self.user, self.employee_bob)
        self.assertEqual(bob.name, 'Bob Test')
        with self.assertRaises(AccessError):
            bob.private_street  # noqa: B018

    def test_user_reads_own_consent_and_exception_only(self):
        consents = self.Consent.with_user(self.user).search([])
        self.assertEqual(consents, self.alice_consent)
        exceptions = self.Exception_.with_user(self.user).search([])
        self.assertEqual(exceptions, self.alice_exception)
        self.assertTrue(self._as(self.user, self.alice_consent).has_access('read'))
        self.assertFalse(self._as(self.user, self.bob_consent).has_access('read'))
        self.assertFalse(self._as(self.user, self.bob_exception).has_access('read'))
        # The chatter of the own consent (grant tracking) is readable.
        messages = self.env['mail.message'].with_user(self.user).search([
            ('model', '=', 'eh.hr.consent'), ('res_id', '=', self.alice_consent.id)])
        self.assertTrue(messages)

    def test_user_cannot_grant_or_withdraw_consent(self):
        pending = self.Consent.create({
            'employee_id': self.employee_alice.id,
            'consent_type': 'photo',
            'company_id': self.company.id,
        })
        with self.assertRaises(AccessError):
            self._as(self.user, pending).action_grant()
        with self.assertRaises(AccessError):
            self._as(self.user, self.alice_consent).action_withdraw()
        with self.assertRaises(AccessError):
            self.Consent.with_user(self.user).create({
                'employee_id': self.employee_alice.id,
                'consent_type': 'voice',
                'company_id': self.company.id,
            })

    def test_user_lists_kiosk_sites(self):
        Site = self.Site.with_user(self.user)
        self.assertIn(self.site, Site.search([]))
        self.assertIn(self.site.id, [site_id for site_id, _name in Site.name_search('Test')])
        rows = Site.web_search_read([], {'name': {}, 'code': {}, 'timezone': {}})['records']
        self.assertIn('test-hq', [row['code'] for row in rows])
        with self.assertRaises(AccessError):
            self._as(self.user, self.site).write({'name': 'Renamed by a staff member'})
        # Terminals, with their tokens, and the audit log stay out of reach.
        self.assertFalse(self._as(self.user, self.device).has_access('read'))
        self.assertFalse(self._as(self.user, self.event).has_access('read'))

    def test_user_records_own_attendance_only(self):
        Attendance = self.env['hr.attendance'].with_user(self.user)
        own = Attendance.create({
            'employee_id': self.employee_alice.id,
            'check_in': datetime(2026, 5, 5, 9),
        })
        own.write({'check_out': datetime(2026, 5, 5, 17)})
        self.assertEqual(own.check_out, datetime(2026, 5, 5, 17))
        self.assertEqual(Attendance.search([]), own)
        with self.assertRaises(AccessError):
            Attendance.create({
                'employee_id': self.employee_bob.id,
                'check_in': datetime(2026, 5, 5, 9),
            })
        with self.assertRaises(AccessError):
            self._as(self.user, self.bob_attendance).write({'check_out': datetime(2026, 5, 4, 18)})
        with self.assertRaises(AccessError):
            self._as(self.user, own).unlink()

    # ------------------------------------------------------------------
    # EH Attendance Auditor: every log, read only
    # ------------------------------------------------------------------
    def test_auditor_reads_every_audit_log(self):
        for record in (self.alice_consent, self.bob_consent, self.alice_exception,
                       self.bob_exception, self.event, self.site, self.device):
            as_auditor = self._as(self.auditor, record)
            self.assertTrue(as_auditor.has_access('read'), record)
            self.assertTrue(as_auditor.display_name, record)
        self.assertEqual(
            self.Consent.with_user(self.auditor).search([]),
            self.alice_consent | self.bob_consent)

    def test_auditor_is_read_only(self):
        """The label says read only: every write, create and delete on the
        audit logs, the kiosk registry, consent and employees is refused."""
        auditor = self.auditor
        for record, vals in (
            (self.alice_consent, {'notes': 'tampered'}),
            (self.bob_exception, {'resolution_notes': 'tampered'}),
            (self.event, {'notes': 'tampered'}),
            (self.site, {'name': 'tampered'}),
            (self.device, {'notes': 'tampered'}),
            (self.employee_bob, {'private_street': 'tampered'}),
            (self.employee_auditor, {'private_street': 'tampered'}),
            (self.bob_attendance, {'check_out': datetime(2026, 5, 4, 18)}),
        ):
            as_auditor = self._as(auditor, record)
            self.assertFalse(as_auditor.has_access('write'), record)
            self.assertFalse(as_auditor.has_access('unlink'), record)
            with self.assertRaises(AccessError, msg=record):
                as_auditor.write(vals)
            with self.assertRaises(AccessError, msg=record):
                as_auditor.unlink()
        with self.assertRaises(AccessError):
            self._as(auditor, self.alice_consent).action_withdraw()
        with self.assertRaises(AccessError):
            self._as(auditor, self.bob_exception).action_resolve()
        with self.assertRaises(AccessError):
            self._as(auditor, self.device).action_revoke()
        for model, vals in (
            ('eh.hr.consent', {'employee_id': self.employee_bob.id, 'consent_type': 'voice'}),
            ('eh.hr.kiosk.site', {'name': 'Auditor site', 'code': 'auditor-site'}),
            ('eh.hr.kiosk.terminal', {'name': 'Auditor kiosk', 'site_id': self.site.id}),
            ('eh.hr.kiosk.event', {'event_type': 'error'}),
            ('eh.hr.attendance.exception', {'employee_id': self.employee_bob.id, 'exception_type': 'manual'}),
            ('hr.employee', {'name': 'Created by the auditor'}),
            ('hr.attendance', {'employee_id': self.employee_bob.id, 'check_in': datetime(2026, 5, 6, 9)}),
        ):
            with self.assertRaises(AccessError, msg=model):
                self.env[model].with_user(auditor).create(vals)
        self.assertFalse(self.employee_bob.private_street)
        self.assertEqual(self.bob_consent.state, 'granted')

    # ------------------------------------------------------------------
    # The screens each role reaches
    # ------------------------------------------------------------------
    def _arch_fields(self, arch):
        """The field names of a view, not those of an embedded subview."""
        root = etree.fromstring(arch)
        names = []
        for node in root.iter('field'):
            parent = node.getparent()
            while parent is not None and parent is not root and parent.tag != 'field':
                parent = parent.getparent()
            if parent is root:
                names.append(node.get('name'))
        return names

    def _specification(self, model, names):
        spec = {}
        for name in names:
            field = model._fields.get(name)
            if field is None:
                continue
            if field.type in ('many2one', 'one2many', 'many2many'):
                spec[name] = {'fields': {'display_name': {}}}
            else:
                spec[name] = {}
        return spec

    def _open_screens(self, user):
        """Open every screen of this suite the user reaches from the People
        Operations menu, as the web client does. Returns {menu xmlid: ids}."""
        self.env.flush_all()
        self.env.invalidate_all()
        env = self.env(user=user)
        root = self.env.ref('eh_hr_attendance_base.menu_eh_hr_root')
        opened = {}
        for menu in env['ir.ui.menu'].load_menus(False).values():
            if (not isinstance(menu, dict) or menu.get('app_id') != root.id
                    or menu.get('action_model') != 'ir.actions.act_window'
                    or menu['xmlid'].split('.')[0] not in SUITE_MODULES):
                continue
            # The web client loads the action as superuser (/web/action/load).
            action = env['ir.actions.act_window'].browse(menu['action_id']).sudo()
            eval_context = {'uid': user.id, 'datetime': datetime, 'context_today': fields.Date.context_today}
            context = safe_eval(action.context or '{}', eval_context)
            domain = safe_eval(action.domain or '[]', {**eval_context, 'context': context})
            model = env[action.res_model].with_context(context)
            modes = action.view_mode.split(',')
            views = model.get_views(
                [(False, mode) for mode in modes] + [(action.search_view_id.id, 'search')],
                {'load_filters': True, 'toolbar': True})['views']
            records = model.web_search_read(
                domain, self._specification(model, self._arch_fields(views['list']['arch'])),
                limit=80)['records']
            ids = [row['id'] for row in records]
            if 'form' in views and ids:
                model.browse(ids).web_read(
                    self._specification(model, self._arch_fields(views['form']['arch'])))
            for node in etree.fromstring(views['search']['arch']).iter('filter'):
                group_by = safe_eval(node.get('context') or '{}').get('group_by')
                if group_by:
                    model.web_read_group(domain, [group_by], ['__count'])
            opened[menu['xmlid']] = ids
        return opened

    def test_user_screens(self):
        opened = self._open_screens(self.user)
        self.assertEqual(set(opened), {'eh_hr_attendance_base.menu_eh_hr_consent'})
        self.assertEqual(opened['eh_hr_attendance_base.menu_eh_hr_consent'], self.alice_consent.ids)

    def test_auditor_screens(self):
        opened = self._open_screens(self.auditor)
        expected = {
            'eh_hr_attendance_base.menu_eh_hr_kiosk_sites',
            'eh_hr_attendance_base.menu_eh_hr_kiosk_devices',
            'eh_hr_attendance_base.menu_eh_hr_kiosk_events',
            'eh_hr_attendance_base.menu_eh_hr_consent',
            'eh_hr_attendance_base.menu_eh_hr_exceptions',
        }
        if 'eh.hr.face.template' in self.env:
            expected.add('eh_hr_face_kiosk.menu_eh_hr_face_templates')
        self.assertEqual(set(opened), expected)
        consent_ids = opened['eh_hr_attendance_base.menu_eh_hr_consent']
        self.assertIn(self.bob_consent.id, consent_ids)
        self.assertIn(self.alice_consent.id, consent_ids)
        self.assertIn(self.event.id, opened['eh_hr_attendance_base.menu_eh_hr_kiosk_events'])
        self.assertIn(self.bob_exception.id, opened['eh_hr_attendance_base.menu_eh_hr_exceptions'])


@tagged('post_install', '-at_install')
class TestOwnAttendanceFlow(HttpCase):
    """A user holding only EH Attendance User checks in and out from the
    systray, the way a staff member does, and edits their own draft
    attendance."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env, login='eh_least_flow_user',
            groups='base.group_user,eh_hr_attendance_base.group_eh_hr_user',
            company_id=cls.env.company.id)
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Flow Test',
            'company_id': cls.env.company.id,
            'user_id': cls.user.id,
        })

    def test_systray_check_in_and_out(self):
        self.assertFalse(self.user.has_group('hr.group_hr_user'))
        self.authenticate('eh_least_flow_user', 'eh_least_flow_user')
        Attendance = self.env['hr.attendance']

        self.make_jsonrpc_request('/hr_attendance/systray_check_in_out', {})
        attendance = Attendance.search([('employee_id', '=', self.employee.id)])
        self.assertEqual(len(attendance), 1)
        self.assertFalse(attendance.check_out)

        data = self.make_jsonrpc_request('/hr_attendance/attendance_user_data', {})
        self.assertEqual(data['attendance_state'], 'checked_in')

        self.make_jsonrpc_request('/hr_attendance/systray_check_in_out', {})
        attendance.invalidate_recordset()
        self.assertTrue(attendance.check_out)
        self.assertEqual(Attendance.search_count([('employee_id', '=', self.employee.id)]), 1)

    def test_edit_own_draft_attendance_in_a_week_with_earlier_shifts(self):
        """Editing an own draft attendance refreshes whatever the rest of the
        week derives from it, which must not need HR rights. Tuesday and
        Wednesday of one week, so the earlier shift is always a sibling."""
        Attendance = self.env['hr.attendance']
        Attendance.create({
            'employee_id': self.employee.id,
            'check_in': datetime(2026, 5, 5, 9),
            'check_out': datetime(2026, 5, 5, 17),
        })
        wednesday = Attendance.create({
            'employee_id': self.employee.id,
            'check_in': datetime(2026, 5, 6, 9),
            'check_out': datetime(2026, 5, 6, 17),
        })
        self.env.flush_all()
        self.env.invalidate_all()
        wednesday.with_user(self.user).write({'check_out': datetime(2026, 5, 6, 16)})
        self.assertEqual(wednesday.check_out, datetime(2026, 5, 6, 16))
