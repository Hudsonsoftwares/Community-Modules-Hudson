# -*- encoding: utf-8 -*-
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import fields
from odoo.tools import mute_logger

from odoo.addons.eh_hr_attendance_base.tests.common import EhHrTestCommon


class TestConsentCascade(EhHrTestCommon):

    def test_withdraw_face_consent_deactivates_templates(self):
        template = self._seed_face_template(self.employee_alice, seed=10)
        consent = template.consent_id
        self.assertTrue(template.active)

        consent.action_withdraw()
        template.invalidate_recordset(['active'])
        self.assertFalse(template.active)

    def test_withdraw_logs_audit_cascade(self):
        template = self._seed_face_template(self.employee_alice, seed=11)
        consent = template.consent_id

        consent.action_withdraw()

        events = self.Event.search([
            ('event_type', '=', 'consent_withdraw'),
            ('employee_id', '=', self.employee_alice.id),
        ])
        self.assertTrue(events)
        cascade_events = events.filtered(lambda e: 'deactivated' in (e.notes or ''))
        self.assertTrue(cascade_events)

    def test_non_face_consent_withdrawal_does_not_touch_templates(self):
        face_template = self._seed_face_template(self.employee_alice, seed=12)
        non_face = self.Consent.create({
            'employee_id': self.employee_alice.id,
            'consent_type': 'fingerprint',
            'company_id': self.company.id,
        })
        non_face.action_grant()
        non_face.action_withdraw()

        face_template.invalidate_recordset(['active'])
        self.assertTrue(face_template.active)

    def test_retention_sweep_expiry_also_deactivates_templates(self):
        template = self._seed_face_template(self.employee_alice, seed=13)
        consent = template.consent_id
        consent.write({'expires_on': fields.Datetime.now() - timedelta(days=1)})
        self.Consent._cron_retention_sweep()
        template.invalidate_recordset(['active'])
        consent.invalidate_recordset(['state'])
        self.assertEqual(consent.state, 'expired')
        self.assertFalse(template.active)


class TestConsentRetentionSweepBatch(EhHrTestCommon):
    """The face kiosk override of the consent retention sweep takes the
    keywords of the base sweep and passes them through. It used to be declared
    without them, so any caller bounding the run with batch_limit (the base
    cron tests, an administrator draining a backlog) broke with a TypeError as
    soon as this module was installed, and its own pass was unbounded."""

    def _expired_face_templates(self, count):
        templates = self.env['eh.hr.face.template']
        for index in range(count):
            template = self._seed_face_template(self.employee_alice, seed=20 + index)
            template.consent_id.write({'expires_on': fields.Datetime.now() - timedelta(days=1)})
            templates |= template
        return templates

    def test_batch_limit_reaches_the_base_pass(self):
        templates = self._expired_face_templates(3)
        consents = templates.consent_id

        self.Consent._cron_retention_sweep(batch_limit=1)
        self.env.invalidate_all()
        expired = consents.filtered(lambda c: c.state == 'expired')
        self.assertEqual(len(expired), 1)
        self.assertEqual(templates.filtered(lambda t: not t.active).consent_id, expired)

        self.Consent._cron_retention_sweep(batch_limit=5)
        self.env.invalidate_all()
        self.assertTrue(all(c.state == 'expired' for c in consents))
        self.assertFalse(any(templates.mapped('active')))

    def test_template_pass_is_bounded_by_the_batch_limit(self):
        """A backlog of expired consents whose templates are still active
        (the state a database is left in when the cron could not run) is
        worked through one batch at a time."""
        templates = self._expired_face_templates(3)
        templates.consent_id.write({'state': 'expired'})

        self.Consent._cron_retention_sweep(batch_limit=1)
        self.env.invalidate_all()
        self.assertEqual(len(templates.filtered(lambda t: not t.active)), 1)

        self.Consent._cron_retention_sweep(batch_limit=2)
        self.env.invalidate_all()
        self.assertFalse(any(templates.mapped('active')))

    def test_cron_reports_the_backlog_with_the_face_pass_installed(self):
        """The base's progress report is unchanged by this module."""
        templates = self._expired_face_templates(3)
        cron_record = self.env.ref('eh_hr_attendance_base.cron_eh_hr_consent_retention_sweep')
        with self.registry_test_mode(), self.registry.cursor() as cr:
            cron = cron_record.with_env(self.env(cr=cr))
            cron, progress = cron.with_context(cron_id=cron.id)._add_progress()
            cron.env['eh.hr.consent'].with_context(**cron.env.context)._cron_retention_sweep(batch_limit=1)
            reported = (progress.done, progress.remaining)
        self.env.invalidate_all()
        self.assertEqual(reported, (1, 2))
        self.assertEqual(len(templates.filtered(lambda t: not t.active)), 1)


class TestConsentRetentionPurge(EhHrTestCommon):
    """A withdrawn face consent past the company retention window is purged
    with its face templates. The template's link to its consent is
    ondelete='restrict', so before this the purge failed on the first such
    consent, rolled back the whole run and failed again every day."""

    def _age(self, consent, days):
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE eh_hr_consent SET write_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(days=days), consent.id))
        self.env.invalidate_all()

    def test_purge_deletes_the_templates_of_a_stale_consent(self):
        stale_template = self._seed_face_template(self.employee_alice, seed=40)
        stale = stale_template.consent_id
        recent_template = self._seed_face_template(self.employee_bob, seed=41)
        recent = recent_template.consent_id
        (stale | recent).action_withdraw()
        self._age(stale, 365 * 3)

        self.Consent._cron_retention_sweep()

        self.assertFalse(stale.exists())
        self.assertFalse(stale_template.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(recent_template.exists())
        self.assertFalse(recent_template.active)

    def test_a_consent_holding_templates_still_cannot_be_deleted_by_hand(self):
        template = self._seed_face_template(self.employee_alice, seed=42)
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), \
                self.env.cr.savepoint():
            template.consent_id.unlink()
        self.assertTrue(template.exists())
