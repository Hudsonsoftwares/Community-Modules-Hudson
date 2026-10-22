# -*- encoding: utf-8 -*-
"""Face templates and the kiosk credential, driven through the entry points
a client really uses: /web/dataset/call_kw and /web/dataset/call_button as
the logged in role, and the public face match route.

A device token and an enrolled embedding together are enough to clock that
employee in or out through /eh_hr/kiosk/face/match. The read only auditor
used to read both over RPC (the views hid them, nothing else did) and so could
post attendance for any colleague. The auditor and the manager now read the
template registry as metadata, the vector and the token are for the Admin
role only, and the kiosk itself, the enrolment wizard and the administrator
keep working.
"""
import json
import random

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

# The template screens: list and form, without the admin only Embedding page.
TEMPLATE_METADATA = {
    'employee_id': {'fields': {'display_name': {}}},
    'consent_id': {'fields': {'display_name': {}}},
    'captured_on': {},
    'captured_via': {},
    'quality_score': {},
    'model_name': {},
    'embedding_dim': {},
    'active': {},
}


def _unit_vector(seed):
    rng = random.Random(seed)
    vec = [rng.uniform(-1.0, 1.0) for _ in range(128)]
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec]


@tagged('post_install', '-at_install')
class TestFaceRoleEntryPoints(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        company = env.company
        cls.role_users = {
            role: new_test_user(
                env,
                login='eh_face_rpc_%s' % role,
                groups='base.group_user,%s' % group,
                company_id=company.id,
            )
            for role, group in ROLE_GROUPS.items()
        }
        cls.site = env['eh.hr.kiosk.site'].create({
            'name': 'Face Rpc HQ',
            'code': 'face-rpc-hq',
            'company_id': company.id,
        })
        cls.device = env['eh.hr.kiosk.terminal'].create({
            'name': 'Face Rpc kiosk',
            'site_id': cls.site.id,
        })
        cls.employee_staff = env['hr.employee'].create({
            'name': 'Face Rpc Staff',
            'company_id': company.id,
            'user_id': cls.role_users['user'].id,
        })
        cls.employee_bob = env['hr.employee'].create({
            'name': 'Face Rpc Bob',
            'company_id': company.id,
        })
        cls.bob_embedding = _unit_vector(7)
        cls.bob_template = cls._enrol(cls.employee_bob, cls.bob_embedding)
        cls.staff_template = cls._enrol(cls.employee_staff, _unit_vector(8))

    @classmethod
    def _enrol(cls, employee, embedding):
        consent = cls.env['eh.hr.consent'].create({
            'employee_id': employee.id,
            'consent_type': 'face',
            'company_id': employee.company_id.id,
        })
        consent.action_grant()
        return cls.env['eh.hr.face.template'].create({
            'employee_id': employee.id,
            'consent_id': consent.id,
            'embedding': json.dumps(embedding),
            'embedding_dim': len(embedding),
            'company_id': employee.company_id.id,
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

    def _match(self, token, embedding):
        return self.url_open(
            '/eh_hr/kiosk/face/match',
            data=json.dumps({'embedding': embedding}),
            headers={'Content-Type': 'application/json', 'X-EH-Kiosk-Token': token},
        )

    def _bob_attendances(self):
        return self.env['hr.attendance'].search([('employee_id', '=', self.employee_bob.id)])

    # ------------------------------------------------------------------
    # The escalation, end to end
    # ------------------------------------------------------------------
    @mute_logger('odoo.http')
    def test_auditor_cannot_clock_a_colleague_in(self):
        """The auditor reads everything it may read of the kiosk and of
        Bob's template, the way any client does (search_read with no field
        list returns every readable field), and posts what it got to the
        face match route. It gets neither the token nor the vector, the
        route refuses, and Bob has no attendance."""
        self._login('auditor')
        terminals = self._call_kw(
            'eh.hr.kiosk.terminal', 'search_read', [[['id', '=', self.device.id]]], {})
        templates = self._call_kw(
            'eh.hr.face.template', 'search_read', [[['employee_id', '=', self.employee_bob.id]]], {})
        # The registries themselves stay open to the auditor.
        self.assertEqual([row['id'] for row in terminals], self.device.ids)
        self.assertEqual([row['id'] for row in templates], self.bob_template.ids)

        token = terminals[0].get('device_token') or ''
        embedding = json.loads(templates[0].get('embedding') or '[]') or [0.0] * 128
        response = self._match(token, embedding)
        self.assertEqual(response.status_code, 401, response.text)
        self.assertFalse(self._bob_attendances())
        self.assertNotIn('device_token', terminals[0])
        self.assertNotIn('embedding', templates[0])

        # The kiosk, which holds its token, still clocks Bob in.
        response = self._match(self.device.device_token, self.bob_embedding)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['match'])
        self.assertEqual(response.json()['action'], 'check_in')
        self.assertEqual(len(self._bob_attendances()), 1)

    # ------------------------------------------------------------------
    # The embedding, per role
    # ------------------------------------------------------------------
    @mute_logger('odoo.http')
    def test_only_an_admin_reads_an_embedding(self):
        bob = self.bob_template
        for role, visible in (
            ('user', self.staff_template),
            ('auditor', self.bob_template | self.staff_template),
            ('manager', self.bob_template | self.staff_template),
        ):
            self._login(role)
            own_or_bob = visible[0]
            self._assert_refused(
                self._call_kw, 'eh.hr.face.template', 'search_read',
                [[['id', '=', own_or_bob.id]]], {'fields': ['embedding']},
                msg=role)
            self._assert_refused(
                self._call_kw, 'eh.hr.face.template', 'web_read', [own_or_bob.ids],
                {'specification': {'embedding': {}}},
                msg=role)
            self._assert_refused(
                self._call_kw, 'eh.hr.face.template', 'get_embedding_as_list', [own_or_bob.ids],
                msg=role)
            self._assert_refused(
                self._call_kw, 'eh.hr.face.template', 'search_count',
                [[['embedding', '=like', '[0%']]],
                msg=role)
            # The metadata screens still open, on the templates the role
            # may see.
            rows = self._call_kw('eh.hr.face.template', 'web_search_read', [[
                ['employee_id', 'in', (self.employee_bob | self.employee_staff).ids],
            ]], {'specification': TEMPLATE_METADATA})['records']
            self.assertEqual(sorted(row['id'] for row in rows), sorted(visible.ids), role)
            self._call_kw('eh.hr.face.template', 'web_read', [visible.ids], {
                'specification': TEMPLATE_METADATA})
            fields = self._call_kw('eh.hr.face.template', 'fields_get', [], {'attributes': ['type']})
            self.assertNotIn('embedding', fields, role)
            self.assertIn('captured_via', fields, role)

        # The administrator reads the vector, as the form's Embedding page does.
        self._login('admin')
        rows = self._call_kw('eh.hr.face.template', 'search_read', [[['id', '=', bob.id]]], {'fields': ['embedding']})
        self.assertEqual(json.loads(rows[0]['embedding']), self.bob_embedding)
        self.assertEqual(
            self._call_kw('eh.hr.face.template', 'get_embedding_as_list', [bob.ids]), self.bob_embedding)

    def test_manager_still_enrols_a_face(self):
        """Enrolment stores a vector the manager may not read back: the
        wizard writes the template as the server, after its own checks."""
        employee = self.env['hr.employee'].create({
            'name': 'Face Rpc Carol',
            'company_id': self.env.company.id,
        })
        samples = [{'embedding': _unit_vector(seed), 'quality': 0.9} for seed in (11, 12, 13)]
        self._login('manager')
        wizard_id = self._call_kw('eh.hr.face.enrolment', 'create', [{
            'employee_id': employee.id,
            'consent_acknowledged': True,
            'samples_json': json.dumps(samples),
        }])
        action = self._call_button('eh.hr.face.enrolment', 'action_grant_consent_and_enrol', [wizard_id])
        self.assertEqual(action['params']['type'], 'success')
        templates = self.env['eh.hr.face.template'].search([('employee_id', '=', employee.id)])
        self.assertEqual(len(templates), 3)
        self.assertEqual(templates.consent_id.state, 'granted')
        self.assertTrue(employee.eh_face_enrolled)
        # And the kiosk matches Carol with one of them.
        response = self._match(self.device.device_token, samples[0]['embedding'])
        self.assertEqual(response.json()['employee_id'], employee.id)
