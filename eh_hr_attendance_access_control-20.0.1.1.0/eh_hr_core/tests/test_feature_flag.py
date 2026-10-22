# -*- coding: utf-8 -*-
"""Feature flags gate engine rollouts, so every scope the flag supports has
to answer the same way on every Odoo the platform runs on."""
from datetime import timedelta

import psycopg2

from odoo import fields
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.eh_hr_compat import groups_field


@tagged('post_install', '-at_install', 'eh_hr', 'eh_hr_platform')
class TestFeatureFlag(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Flag = cls.env['eh.hr.feature.flag']

    def test_an_unknown_or_disabled_flag_is_off(self):
        self.assertFalse(self.Flag.is_enabled('probe.unknown'))
        self.Flag.create({'code': 'probe.off', 'enabled': False})
        self.assertFalse(self.Flag.is_enabled('probe.off'))

    def test_an_enabled_flag_is_on(self):
        self.Flag.create({'code': 'probe.on', 'enabled': True})
        self.assertTrue(self.Flag.is_enabled('probe.on'))

    def test_a_company_scoped_flag_only_fires_in_that_company(self):
        other = self.env['res.company'].create({'name': 'EH flag co B'})
        self.Flag.create({'code': 'probe.company', 'enabled': True,
                          'company_ids': [(6, 0, [other.id])]})
        self.assertFalse(self.Flag.is_enabled('probe.company'))
        in_other = self.Flag.with_company(other)
        self.assertTrue(in_other.is_enabled('probe.company'),
                        'The flag must fire in the company it is scoped to.')

    def test_a_group_scoped_flag_only_fires_for_members(self):
        group = self.env['res.groups'].create({'name': 'EH flag group'})
        self.Flag.create({'code': 'probe.group', 'enabled': True,
                          'group_ids': [(6, 0, [group.id])]})
        self.assertFalse(self.Flag.is_enabled('probe.group'),
                         'A non-member must not see the feature.')
        self.env.user.write({groups_field(self.env): [(4, group.id)]})
        self.env.invalidate_all()
        self.assertTrue(self.Flag.is_enabled('probe.group'))

    def test_the_validity_window_opens_and_closes_the_flag(self):
        now = fields.Datetime.now()
        self.Flag.create({'code': 'probe.future', 'enabled': True,
                          'valid_from': now + timedelta(days=1)})
        self.Flag.create({'code': 'probe.past', 'enabled': True,
                          'valid_to': now - timedelta(days=1)})
        self.Flag.create({'code': 'probe.window', 'enabled': True,
                          'valid_from': now - timedelta(days=1),
                          'valid_to': now + timedelta(days=1)})
        self.assertFalse(self.Flag.is_enabled('probe.future'))
        self.assertFalse(self.Flag.is_enabled('probe.past'))
        self.assertTrue(self.Flag.is_enabled('probe.window'))

    def test_a_percentage_rollout_is_deterministic_per_user(self):
        self.Flag.create({'code': 'probe.none', 'enabled': True,
                          'rollout_percent': 0})
        self.assertFalse(self.Flag.is_enabled('probe.none'),
                         'A zero percent rollout reaches nobody.')
        self.Flag.create({'code': 'probe.half', 'enabled': True,
                          'rollout_percent': 50})
        answers = {self.Flag.is_enabled('probe.half') for _ in range(5)}
        self.assertEqual(len(answers), 1,
                         'One user must always get the same answer.')

    def test_the_flag_code_is_unique(self):
        self.Flag.create({'code': 'probe.dup', 'enabled': True})
        with mute_logger('odoo.sql_db'), \
                self.assertRaises(psycopg2.IntegrityError):
            self.Flag.create({'code': 'probe.dup'})
            self.env.flush_all()
