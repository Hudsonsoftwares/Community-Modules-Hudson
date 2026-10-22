# -*- encoding: utf-8 -*-
"""Scheduled action proofs for the attendance engine.

The retention sweeps are the only production code that nothing but the
scheduler calls. Calling the Python method directly proves the sweep but not
the binding between the shipped ir.cron record, its server action code string
and the model, nor the progress the scheduler reads to decide whether to run
the job again.

Both are exercised here the way ir.cron runs them. The sweeps call
ir.cron._commit_progress, which commits, and Odoo 20 refuses a commit on the
cursor of a test case, so the run happens on a registry cursor exactly as
Odoo's own cron tests do.
"""
from datetime import timedelta

from odoo import fields

from .common import EhHrTestCommon


class TestRetentionCrons(EhHrTestCommon):

    def _run_cron(self, xmlid):
        """Run a shipped cron the way the scheduler does: the server action
        code string with `model` bound, under a context carrying cron_id and
        the progress record. Returns the (done, remaining) it reported.
        """
        cron_record = self.env.ref(xmlid)
        with self.registry_test_mode(), self.registry.cursor() as cr:
            cron = cron_record.with_env(self.env(cr=cr))
            cron, progress = cron.with_context(cron_id=cron.id)._add_progress()
            cron._callback(cron.cron_name, cron.ir_actions_server_id.id)
            reported = (progress.done, progress.remaining)
        self.env.invalidate_all()
        return reported

    def _run_sweep(self, model_name, xmlid, **kwargs):
        """Run a sweep under the same cron context, with arguments the code
        string cannot pass. Returns the (done, remaining) it reported.
        """
        cron_record = self.env.ref(xmlid)
        with self.registry_test_mode(), self.registry.cursor() as cr:
            cron = cron_record.with_env(self.env(cr=cr))
            cron, progress = cron.with_context(cron_id=cron.id)._add_progress()
            model = cron.env[model_name].with_context(**cron.env.context)
            model._cron_retention_sweep(**kwargs)
            reported = (progress.done, progress.remaining)
        self.env.invalidate_all()
        return reported

    def test_consent_cron_record_expires_past_due_grants(self):
        consent = self._grant_face_consent(self.employee_alice)
        consent.write({'expires_on': fields.Datetime.now() - timedelta(days=1)})

        done, remaining = self._run_cron(
            'eh_hr_attendance_base.cron_eh_hr_consent_retention_sweep')

        self.assertEqual(consent.state, 'expired')
        self.assertGreaterEqual(done, 1)
        self.assertEqual(remaining, 0)

    def test_consent_cron_reports_the_backlog_it_left(self):
        """A batch smaller than the backlog reports the rest as remaining, so
        the framework reschedules the job instead of waiting a full day.
        """
        now = fields.Datetime.now()
        consents = self.Consent
        for _index in range(3):
            consent = self._grant_face_consent(self.employee_alice)
            consent.write({'expires_on': now - timedelta(days=1)})
            consents |= consent

        done, remaining = self._run_sweep(
            'eh.hr.consent',
            'eh_hr_attendance_base.cron_eh_hr_consent_retention_sweep',
            batch_limit=1,
        )

        self.assertEqual(done, 1)
        self.assertEqual(remaining, 2)
        self.assertEqual(len(consents.filtered(lambda c: c.state == 'expired')), 1)

    def test_audit_cron_record_trims_old_events(self):
        event = self.Event.log('error', company_id=self.company.id)
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE eh_hr_kiosk_event SET timestamp = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(days=365 * 10), event.id),
        )
        self.Event.invalidate_model()

        done, remaining = self._run_cron(
            'eh_hr_attendance_base.cron_eh_hr_audit_retention_sweep')

        self.assertFalse(self.Event.browse(event.id).exists())
        self.assertGreaterEqual(done, 1)
        self.assertEqual(remaining, 0)

    def test_audit_cron_reports_the_backlog_it_left(self):
        events = self.Event
        for _index in range(3):
            events |= self.Event.log('error', company_id=self.company.id)
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE eh_hr_kiosk_event SET timestamp = %s WHERE id IN %s",
            (fields.Datetime.now() - timedelta(days=365 * 10), tuple(events.ids)),
        )
        self.Event.invalidate_model()

        done, remaining = self._run_sweep(
            'eh.hr.kiosk.event',
            'eh_hr_attendance_base.cron_eh_hr_audit_retention_sweep',
            batch_limit=1,
        )

        self.assertEqual(done, 1)
        self.assertEqual(remaining, 2)
        self.assertEqual(len(events.exists()), 2)

    def test_consent_sweep_deletes_only_past_the_retention_horizon(self):
        """The second pass deletes withdrawn rows past the company horizon and
        leaves recent ones alone.
        """
        stale = self._grant_face_consent(self.employee_alice)
        stale.action_withdraw()
        recent = self._grant_face_consent(self.employee_bob)
        recent.action_withdraw()
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE eh_hr_consent SET write_date = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(days=365 * 3), stale.id),
        )
        self.Consent.invalidate_model()

        self.Consent._cron_retention_sweep()

        self.assertFalse(self.Consent.browse(stale.id).exists())
        self.assertTrue(recent.exists())
