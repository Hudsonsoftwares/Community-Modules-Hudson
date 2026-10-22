# -*- coding: utf-8 -*-
"""The two knobs the platform exposes in Settings and the one scheduled action
it ships. Odoo 20 replaced the untyped config parameter accessors with typed
ones, so the round trip is asserted rather than assumed, and the cron body is
executed the way ir.cron executes it."""
import time

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eh_hr', 'eh_hr_platform')
class TestPlatformSettings(TransactionCase):

    def test_the_settings_round_trip_through_config_parameters(self):
        settings = self.env['res.config.settings'].create({
            'hr_audit_retention_days': 365,
            'hr_pii_redact_in_exports': False,
        })
        settings.execute()
        params = self.env['ir.config_parameter'].sudo()
        self.assertEqual(params.get_int('eh_hr_core.audit_retention_days'), 365)
        self.assertFalse(params.get_bool('eh_hr_core.pii_redact_in_exports'))
        reopened = self.env['res.config.settings'].create({})
        self.assertEqual(reopened.hr_audit_retention_days, 365,
                         'The saved value must come back into the form.')
        self.assertFalse(reopened.hr_pii_redact_in_exports)


@tagged('post_install', '-at_install', 'eh_hr', 'eh_hr_platform')
class TestRateLimitVacuum(TransactionCase):

    def test_the_cron_record_runs_and_clears_closed_windows(self):
        limiter = self.env['eh.hr.rate.limit']
        limiter.hit('probe.cron', 'caller', 5, 60)
        old = limiter.create({
            'scope': 'probe.cron', 'key': 'stale',
            'window_start': int(time.time()) - 7200, 'hits': 1})
        cron = self.env.ref('eh_hr_core.cron_eh_hr_rate_limit_gc')
        self.assertEqual(cron.state, 'code')
        # Run the stored code exactly as ir.cron does.
        eval_context = {'model': self.env[cron.model_id.model],
                        'env': self.env}
        exec(cron.code, dict(eval_context))  # noqa: S102
        self.env.invalidate_all()
        self.assertFalse(old.exists(),
                         'A window that closed hours ago must be vacuumed.')
        self.assertTrue(limiter.search(
            [('scope', '=', 'probe.cron'), ('key', '=', 'caller')]),
            'The current window must survive the vacuum.')
