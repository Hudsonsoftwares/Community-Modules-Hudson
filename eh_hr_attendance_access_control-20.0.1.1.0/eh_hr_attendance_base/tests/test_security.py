# -*- encoding: utf-8 -*-
"""Role, record and company scoping proofs for the attendance engine.

The Odoo 19 ir.model.access rows and the ir.rule records were folded into a
single ir.access file on Odoo 20. Counting rows proves nothing there: a role
row disappears whenever an implied group already grants the same operations,
and a permission row now carries the record domain that used to live in a
rule. Every privilege level is therefore proven here by calling has_access on
the model and by reading real rows as each role.
"""
from odoo.exceptions import AccessError
from odoo.tests import new_test_user

from .common import EhHrTestCommon


ROLE_GROUPS = {
    'user': 'eh_hr_attendance_base.group_eh_hr_user',
    'manager': 'eh_hr_attendance_base.group_eh_hr_manager',
    'admin': 'eh_hr_attendance_base.group_eh_hr_admin',
    'auditor': 'eh_hr_attendance_base.group_eh_hr_auditor',
}

# Operations each role may perform on each model, as the Odoo 19 ACL rows and
# record rules granted them. 'c' create, 'r' read, 'u' write, 'd' unlink.
# One deliberate change since 19: the manager reads the kiosk terminals but no
# longer writes them, because renaming, moving and revoking a terminal is
# Admin configuration, as the terminal form and the Admin role say.
ROLE_MATRIX = {
    'eh.hr.consent': {'user': 'r', 'manager': 'cru', 'admin': 'crud', 'auditor': 'r'},
    'eh.hr.kiosk.site': {'user': 'r', 'manager': 'cru', 'admin': 'crud', 'auditor': 'r'},
    'eh.hr.kiosk.terminal': {'user': '', 'manager': 'r', 'admin': 'crud', 'auditor': 'r'},
    'eh.hr.kiosk.event': {'user': '', 'manager': 'r', 'admin': 'rd', 'auditor': 'r'},
    'eh.hr.attendance.exception': {'user': 'r', 'manager': 'cru', 'admin': 'crud', 'auditor': 'r'},
}

OPERATIONS = {'c': 'create', 'r': 'read', 'u': 'write', 'd': 'unlink'}


class TestAccessMatrix(EhHrTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_users = {
            role: new_test_user(
                cls.env,
                login='eh_hr_%s' % role,
                groups='base.group_user,%s' % group,
                company_id=cls.company.id,
            )
            for role, group in ROLE_GROUPS.items()
        }

    def test_model_access_per_role(self):
        """Every role keeps exactly the model level rights it had on 19."""
        for model, per_role in ROLE_MATRIX.items():
            for role, allowed in per_role.items():
                empty = self.env[model].with_user(self.role_users[role]).browse()
                for letter, operation in OPERATIONS.items():
                    self.assertEqual(
                        empty.has_access(operation),
                        letter in allowed,
                        'role %s on %s: unexpected %s access' % (role, model, operation),
                    )

    def test_user_reads_only_own_consent(self):
        """A plain user sees their own consent rows and nobody else's."""
        self.employee_alice.user_id = self.role_users['user']
        own = self._grant_face_consent(self.employee_alice)
        other = self._grant_face_consent(self.employee_bob)

        as_user = self.Consent.with_user(self.role_users['user'])
        visible = as_user.search([])
        self.assertIn(own, visible)
        self.assertNotIn(other, visible)
        self.assertFalse(other.with_user(self.role_users['user']).has_access('read'))

    def test_user_reads_only_own_exception(self):
        """The same employee scoping applies to attendance exceptions."""
        self.employee_alice.user_id = self.role_users['user']
        own = self.Exception_.raise_exception(
            employee=self.employee_alice, exception_type='late')
        other = self.Exception_.raise_exception(
            employee=self.employee_bob, exception_type='late')

        visible = self.Exception_.with_user(self.role_users['user']).search([])
        self.assertIn(own, visible)
        self.assertNotIn(other, visible)

    def test_manager_reads_every_employee_row(self):
        """A manager is not employee scoped, unlike a plain user."""
        self.employee_alice.user_id = self.role_users['manager']
        own = self._grant_face_consent(self.employee_alice)
        other = self._grant_face_consent(self.employee_bob)

        visible = self.Consent.with_user(self.role_users['manager']).search([])
        self.assertIn(own, visible)
        self.assertIn(other, visible)

    def test_auditor_is_read_only(self):
        """The auditor role reads every log and writes nothing."""
        consent = self._grant_face_consent(self.employee_alice)
        consent.notes = 'Filed by HR.'
        event = self.Event.log('error', notes='Audit probe', company_id=self.company.id)
        auditor = self.role_users['auditor']

        self.assertTrue(consent.with_user(auditor).has_access('read'))
        self.assertTrue(event.with_user(auditor).has_access('read'))
        self.assertEqual(consent.with_user(auditor).notes, 'Filed by HR.')
        self.assertEqual(event.with_user(auditor).notes, 'Audit probe')
        with self.assertRaises(AccessError):
            consent.with_user(auditor).write({'notes': 'tampered'})
        with self.assertRaises(AccessError):
            self.Site.with_user(auditor).create({
                'name': 'Auditor site',
                'code': 'auditor-site',
                'company_id': self.company.id,
            })

    def test_company_restriction_hides_other_company_rows(self):
        """The per company restriction rows still scope every model."""
        other_company = self.Company.create({'name': 'EH Second Company'})
        foreign_site = self.Site.create({
            'name': 'Foreign HQ',
            'code': 'foreign-hq',
            'company_id': other_company.id,
        })
        manager = self.role_users['manager']

        visible = self.Site.with_user(manager).search([])
        self.assertIn(self.site, visible)
        self.assertNotIn(foreign_site, visible)
        self.assertFalse(foreign_site.with_user(manager).has_access('read'))

        # The same manager, once the second company is allowed and activated,
        # sees the row: the restriction scopes by company, it does not hide
        # the model.
        manager.company_ids = [(4, other_company.id)]
        activated = foreign_site.with_user(manager).with_context(
            allowed_company_ids=[self.company.id, other_company.id])
        self.assertTrue(activated.has_access('read'))
        self.assertEqual(activated.name, 'Foreign HQ')

    def test_kiosk_pin_is_manager_only(self):
        """The kiosk PIN keeps its field level restriction on Odoo 20, where
        groups= is enforced on attribute access and not only in read()."""
        field = self.Employee._fields['eh_kiosk_pin']
        as_user = self.employee_alice.with_user(self.role_users['user'])
        as_manager = self.employee_alice.with_user(self.role_users['manager'])

        self.assertFalse(as_user.has_field_access(field, 'read'))
        self.assertTrue(as_manager.has_field_access(field, 'read'))
        with self.assertRaises(AccessError):
            as_user.eh_kiosk_pin  # noqa: B018
