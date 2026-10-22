# -*- encoding: utf-8 -*-
import json

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import new_test_user

from odoo.addons.eh_hr_attendance_base.tests.common import EhHrTestCommon


class TestFaceTemplate(EhHrTestCommon):

    def test_create_template_with_valid_embedding(self):
        consent = self._grant_face_consent(self.employee_alice)
        template = self.env['eh.hr.face.template'].create({
            'employee_id': self.employee_alice.id,
            'consent_id': consent.id,
            'embedding': json.dumps(self._make_embedding(seed=1)),
            'embedding_dim': 128,
            'company_id': self.company.id,
        })
        self.assertTrue(template.id)
        self.assertEqual(template.employee_id, self.employee_alice)
        self.assertTrue(template.active)

    def test_invalid_embedding_json_rejected(self):
        consent = self._grant_face_consent(self.employee_alice)
        with self.assertRaises(ValidationError):
            self.env['eh.hr.face.template'].create({
                'employee_id': self.employee_alice.id,
                'consent_id': consent.id,
                'embedding': 'not-json',
                'embedding_dim': 128,
                'company_id': self.company.id,
            })

    def test_dim_mismatch_rejected(self):
        consent = self._grant_face_consent(self.employee_alice)
        with self.assertRaises(ValidationError):
            self.env['eh.hr.face.template'].create({
                'employee_id': self.employee_alice.id,
                'consent_id': consent.id,
                'embedding': json.dumps([0.1, 0.2, 0.3]),
                'embedding_dim': 128,
                'company_id': self.company.id,
            })

    def test_consent_must_be_face_type(self):
        non_face = self.Consent.create({
            'employee_id': self.employee_alice.id,
            'consent_type': 'fingerprint',
            'company_id': self.company.id,
        })
        non_face.action_grant()
        with self.assertRaises(ValidationError):
            self.env['eh.hr.face.template'].create({
                'employee_id': self.employee_alice.id,
                'consent_id': non_face.id,
                'embedding': json.dumps(self._make_embedding()),
                'embedding_dim': 128,
                'company_id': self.company.id,
            })

    def test_consent_employee_must_match_template_employee(self):
        consent = self._grant_face_consent(self.employee_alice)
        with self.assertRaises(ValidationError):
            self.env['eh.hr.face.template'].create({
                'employee_id': self.employee_bob.id,  # Bob not Alice
                'consent_id': consent.id,
                'embedding': json.dumps(self._make_embedding()),
                'embedding_dim': 128,
                'company_id': self.company.id,
            })

    def test_employee_face_enrolled_compute(self):
        self.assertFalse(self.employee_alice.eh_face_enrolled)
        self._seed_face_template(self.employee_alice)
        self.employee_alice.invalidate_recordset(['eh_face_enrolled', 'eh_face_template_ids'])
        self.assertTrue(self.employee_alice.eh_face_enrolled)
        self.assertEqual(self.employee_alice.eh_face_template_count, 1)

    def test_action_deactivate_and_reactivate(self):
        template = self._seed_face_template(self.employee_alice)
        template.action_deactivate()
        self.assertFalse(template.active)
        template.action_reactivate()
        self.assertTrue(template.active)

    def test_reactivate_blocked_when_consent_not_granted(self):
        template = self._seed_face_template(self.employee_alice)
        template.action_deactivate()
        template.consent_id.action_withdraw()
        with self.assertRaises(ValidationError):
            template.action_reactivate()


class TestFaceTemplateAccess(EhHrTestCommon):
    """A face template is biometric data. The EH Attendance User role, which
    no longer makes its holder an HR Officer, reads the templates of its own
    employee only; the auditor and the manager read every template of their
    companies, as metadata. The embedding itself, the vector a kiosk matches
    against, is readable by the EH Attendance Admin role only."""

    def test_user_reads_own_templates_only(self):
        user, auditor, manager, admin = (
            new_test_user(
                self.env, login='eh_face_%s' % role,
                groups='base.group_user,eh_hr_attendance_base.group_eh_hr_%s' % role,
                company_id=self.company.id)
            for role in ('user', 'auditor', 'manager', 'admin'))
        self.employee_alice.user_id = user
        own = self._seed_face_template(self.employee_alice, seed=30)
        other = self._seed_face_template(self.employee_bob, seed=31)
        self.env.flush_all()
        self.env.invalidate_all()

        Template = self.env['eh.hr.face.template']
        self.assertEqual(Template.with_user(user).search([]), own)
        self.assertFalse(other.with_user(user).has_access('read'))
        with self.assertRaises(AccessError):
            other.with_user(user).embedding  # noqa: B018
        self.assertEqual(own.with_user(user).employee_id, self.employee_alice)
        with self.assertRaises(AccessError):
            own.with_user(user).embedding  # noqa: B018
        for reader in (auditor, manager):
            self.assertEqual(Template.with_user(reader).search([]), own | other, reader.login)
            self.assertEqual(other.with_user(reader).employee_id, self.employee_bob, reader.login)
            with self.assertRaises(AccessError, msg=reader.login):
                other.with_user(reader).embedding  # noqa: B018
        self.assertEqual(Template.with_user(admin).search([]), own | other)
        self.assertEqual(other.with_user(admin).get_embedding_as_list(), self._make_embedding(31))
