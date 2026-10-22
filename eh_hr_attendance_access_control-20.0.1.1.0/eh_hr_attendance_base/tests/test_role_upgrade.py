# -*- encoding: utf-8 -*-
"""The 20.0.1.1.0 upgrade that stops the User and Auditor roles implying HR
Officer without taking HR Officer away from anyone overnight.

A database left by 20.0.1.0.0 is rebuilt here by putting the old implication
back on both roles, then the upgrade script runs on it exactly as the module
update runs it. Every way of holding HR Officer is represented, so a user the
script should have left alone and a user it should have covered both show.
"""
import logging
import re
from pathlib import Path

from odoo.fields import Command
from odoo.modules.module import load_script
from odoo.tests import new_test_user

from .common import EhHrTestCommon

SCRIPT = Path(__file__).resolve().parents[1] / 'migrations' / '20.0.1.1.0' / 'pre-migrate.py'
LOGGER = 'eh_hr_attendance_base_pre_migrate_20_0_1_1_0'


class TestRoleUpgrade(EhHrTestCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = load_script(str(SCRIPT), LOGGER)
        cls.officer = cls.env.ref('hr.group_hr_user')
        cls.eh_user = cls.env.ref('eh_hr_attendance_base.group_eh_hr_user')
        cls.eh_auditor = cls.env.ref('eh_hr_attendance_base.group_eh_hr_auditor')
        # A group of another module that implies the User role.
        cls.site_lead = cls.env['res.groups'].create({
            'name': 'Site lead (test)',
            'implied_ids': [Command.link(cls.eh_user.id)],
        })

        def user(login, groups, **kwargs):
            return new_test_user(
                cls.env, login=login, groups=','.join(['base.group_user', *groups]),
                company_id=cls.company.id, **kwargs)

        cls.covered = {
            'only_user': user('upg_only_user', ['eh_hr_attendance_base.group_eh_hr_user']),
            'only_auditor': user('upg_only_auditor', ['eh_hr_attendance_base.group_eh_hr_auditor']),
            'both_roles': user('upg_both_roles', [
                'eh_hr_attendance_base.group_eh_hr_user',
                'eh_hr_attendance_base.group_eh_hr_auditor']),
            'archived': user('upg_archived', ['eh_hr_attendance_base.group_eh_hr_user']),
            'through_group': user('upg_through_group', []),
        }
        cls.covered['archived'].active = False
        cls.covered['through_group'].group_ids = [Command.link(cls.site_lead.id)]
        cls.untouched = {
            'officer_too': user('upg_officer_too', [
                'eh_hr_attendance_base.group_eh_hr_user', 'hr.group_hr_user']),
            'hr_admin': user('upg_hr_admin', [
                'eh_hr_attendance_base.group_eh_hr_auditor', 'hr.group_hr_manager']),
            'eh_manager': user('upg_eh_manager', ['eh_hr_attendance_base.group_eh_hr_manager']),
            'plain': user('upg_plain', []),
        }

    def _old_security_file(self):
        """Put the database back where 20.0.1.0.0 left it."""
        (self.eh_user | self.eh_auditor).write({'implied_ids': [Command.link(self.officer.id)]})
        self.env.flush_all()

    def _explicit(self, user):
        return user.with_context(active_test=False).group_ids

    def _migrate(self):
        self.env.flush_all()
        with self.assertLogs(LOGGER, 'INFO') as logs:
            self.script.migrate(self.env.cr, '20.0.1.0.0')
        self.env.invalidate_all()
        return '\n'.join(logs.output)

    def test_old_database_has_every_role_holder_as_hr_officer(self):
        """The starting point is the defect itself."""
        self._old_security_file()
        for name, user in self.covered.items():
            self.assertTrue(user.has_group('hr.group_hr_user'), name)
            self.assertNotIn(self.officer, self._explicit(user), name)

    def test_upgrade_keeps_hr_officer_explicitly_and_logs_the_logins(self):
        self._old_security_file()
        before = {name: self._explicit(user) for name, user in self.untouched.items()}

        output = self._migrate()

        # The implication is gone from both roles.
        self.assertNotIn(self.officer, self.eh_user.implied_ids)
        self.assertNotIn(self.officer, self.eh_auditor.implied_ids)
        self.assertNotIn(self.officer, self.eh_user.all_implied_ids)
        # Everyone who held HR Officer only through a role holds it
        # explicitly now, and is named for review.
        for name, user in self.covered.items():
            self.assertIn(self.officer, self._explicit(user), name)
            self.assertTrue(user.has_group('hr.group_hr_user'), name)
            self.assertIn(user.login, output, name)
        # Nobody else is touched or named.
        for name, user in self.untouched.items():
            self.assertEqual(self._explicit(user), before[name], name)
            self.assertNotIn(user.login, output, name)
        self.assertFalse(self.untouched['plain'].has_group('hr.group_hr_user'))
        # Other users of the database may be covered too, never fewer.
        counted = re.search(r'to the (\d+) user\(s\)', output)
        self.assertTrue(counted, output)
        self.assertGreaterEqual(int(counted.group(1)), len(self.covered))

    def test_assignments_after_the_upgrade_are_least_privilege(self):
        self._old_security_file()
        self._migrate()
        fresh_user = new_test_user(
            self.env, login='upg_fresh_user',
            groups='base.group_user,eh_hr_attendance_base.group_eh_hr_user',
            company_id=self.company.id)
        fresh_auditor = new_test_user(
            self.env, login='upg_fresh_auditor',
            groups='base.group_user,eh_hr_attendance_base.group_eh_hr_auditor',
            company_id=self.company.id)
        for user in (fresh_user, fresh_auditor):
            self.assertFalse(user.has_group('hr.group_hr_user'), user.login)
            self.assertFalse(
                self.Employee.with_user(user).browse().has_access('write'), user.login)

    def test_running_it_again_changes_nothing(self):
        self._old_security_file()
        self._migrate()
        after_first = {
            user.id: self._explicit(user)
            for user in [*self.covered.values(), *self.untouched.values()]}

        output = self._migrate()

        self.assertIn('no user held it only through those roles', output)
        for user in [*self.covered.values(), *self.untouched.values()]:
            self.assertEqual(self._explicit(user), after_first[user.id], user.login)

    def test_fresh_database_is_left_alone(self):
        """On a database that never had the implication nobody is named and
        nobody gains HR Officer."""
        output = self._migrate()
        self.assertIn('no user held it only through those roles', output)
        for name, user in self.covered.items():
            self.assertFalse(user.has_group('hr.group_hr_user'), name)

    def test_stale_translated_descriptions_are_dropped(self):
        """The translations of the old descriptions say the roles imply HR
        User. An update rewrites only the English text, so they would stay."""
        roles = self.eh_user | self.eh_auditor
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_groups SET comment = comment || %s::jsonb WHERE id IN %s",
            ['{"fr_FR": "Implique le role standard Utilisateur RH."}', tuple(roles.ids)])
        self._old_security_file()

        self._migrate()

        self.env.cr.execute(
            "SELECT id, comment FROM res_groups WHERE id IN %s", [tuple(roles.ids)])
        for group_id, comment in self.env.cr.fetchall():
            self.assertEqual(set(comment), {'en_US'}, group_id)
            self.assertEqual(comment['en_US'], self.env['res.groups'].browse(group_id).comment)

    def test_script_is_bound_to_this_release(self):
        self.assertTrue(SCRIPT.is_file())
        manifest = (SCRIPT.parents[2] / '__manifest__.py').read_text()
        self.assertIn("'version': '20.0.1.1.0'", manifest)
        self.assertEqual(logging.getLogger(LOGGER).name, self.script._logger.name)
