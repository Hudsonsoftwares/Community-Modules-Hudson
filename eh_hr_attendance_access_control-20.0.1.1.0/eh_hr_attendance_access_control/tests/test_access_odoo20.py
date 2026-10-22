# -*- encoding: utf-8 -*-
"""Odoo 20 proofs for the door access module.

Two things a green suite could not show before:

* The Odoo 19 ACL rows and the four global record rules were folded into one
  ir.access file, and the converter drops any row an implied group already
  covers. Counting rows proves nothing; calling has_access per role and reading
  a second company's rows does.
* The retention cron was production code nothing executed. Running the shipped
  record's own code string is what proves the binding between the data file and
  the model method.
"""
from datetime import timedelta

from odoo import fields
from odoo.tests import new_test_user

from odoo.addons.eh_hr_attendance_base.tests.common import EhHrTestCommon

ROLE_GROUPS = {
    'user': 'eh_hr_attendance_base.group_eh_hr_user',
    'manager': 'eh_hr_attendance_base.group_eh_hr_manager',
    'admin': 'eh_hr_attendance_base.group_eh_hr_admin',
    'auditor': 'eh_hr_attendance_base.group_eh_hr_auditor',
}

# Operations each role had on Odoo 19, read off ir.model.access.csv on the 19.0
# branch. 'c' create, 'r' read, 'u' write, 'd' unlink.
ROLE_MATRIX = {
    'eh.hr.access.zone': {'user': 'r', 'manager': 'cru', 'admin': 'crud', 'auditor': 'r'},
    'eh.hr.access.reader': {'user': '', 'manager': 'r', 'admin': 'crud', 'auditor': 'r'},
    'eh.hr.access.permission': {'user': 'r', 'manager': 'cru', 'admin': 'crud', 'auditor': 'r'},
    'eh.hr.access.event': {'user': '', 'manager': 'r', 'admin': 'rd', 'auditor': 'r'},
}

OPERATIONS = {'c': 'create', 'r': 'read', 'u': 'write', 'd': 'unlink'}


class TestAccessControlSecurity(EhHrTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_users = {
            role: new_test_user(
                cls.env,
                login='eh_access_%s' % role,
                groups='base.group_user,%s' % group,
                company_id=cls.company.id,
            )
            for role, group in ROLE_GROUPS.items()
        }
        cls.zone = cls.env['eh.hr.access.zone'].create({
            'name': 'Matrix door',
            'code': 'matrix-door',
            'company_id': cls.company.id,
        })

    def test_model_access_per_role(self):
        """Every role keeps exactly the model level rights it had on 19."""
        for model, per_role in ROLE_MATRIX.items():
            for role, allowed in per_role.items():
                empty = self.env[model].with_user(self.role_users[role]).browse()
                for letter, operation in OPERATIONS.items():
                    self.assertEqual(
                        empty.has_access(operation),
                        letter in allowed,
                        'role %s on %s: unexpected %s access'
                        % (role, model, operation),
                    )

    def test_company_restriction_hides_another_company_zone(self):
        other_company = self.env['res.company'].create({'name': 'EH Access Co'})
        theirs = self.env['eh.hr.access.zone'].sudo().create({
            'name': 'Their door',
            'code': 'their-door',
            'company_id': other_company.id,
        })
        visible = self.env['eh.hr.access.zone'].with_user(
            self.role_users['manager']).search([])
        self.assertIn(self.zone, visible)
        self.assertNotIn(theirs, visible)

    def test_bearer_token_is_admin_only(self):
        """The token is the door's credential: Odoo 20 enforces a field's
        groups= on attribute access, not only in read()."""
        reader = self.env['eh.hr.access.reader'].create({
            'name': 'Token reader',
            'zone_id': self.zone.id,
            'webhook_url': 'https://bridge.invalid/unlock',
            'bearer_token': 'super-secret',
        })
        field = reader._fields['bearer_token']
        self.assertTrue(
            reader.with_user(self.role_users['admin']).has_field_access(
                field, 'read'))
        self.assertFalse(
            reader.with_user(self.role_users['auditor']).has_field_access(
                field, 'read'))


class TestAccessRetentionCron(EhHrTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Event = cls.env['eh.hr.access.event']
        cls.company.eh_hr_access_retention_days = 30

    def _event(self, age_days):
        event = self.Event.create({
            'employee_id': self.employee_alice.id,
            'outcome': 'allowed',
            'company_id': self.company.id,
        })
        event.created_on = fields.Datetime.now() - timedelta(days=age_days)
        return event

    def test_retention_cron_runs_its_own_code_string(self):
        """The binding between the shipped cron record and the model method is
        production code no other test touches."""
        stale = self._event(age_days=90)
        fresh = self._event(age_days=1)
        cron = self.env.ref(
            'eh_hr_attendance_access_control.'
            'cron_eh_hr_access_event_retention_sweep')

        cron.ir_actions_server_id.run()

        self.assertFalse(stale.exists(),
                         'An event past the retention horizon must be swept.')
        self.assertTrue(fresh.exists(),
                        'An event inside the horizon must survive the sweep.')

    def test_retention_sweep_honours_the_company_horizon(self):
        self.company.eh_hr_access_retention_days = 365
        old_but_inside = self._event(age_days=90)
        self.Event._cron_retention_sweep()
        self.assertTrue(old_but_inside.exists())
