# -*- coding: utf-8 -*-
"""The compatibility layer is the only place the platform is allowed to know
which Odoo it runs on, so every one of its public helpers is exercised here
against the running server rather than asserted from a table of expectations.

Fifty odd feature modules read these helpers, so a silent drift (a renamed
core field, a model that no longer exists) has to fail here first.
"""
from odoo import release
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.eh_hr_compat import (
    CONTRACT_MODEL,
    IS_17_PLUS,
    IS_18_PLUS,
    IS_19_PLUS,
    IS_20_PLUS,
    LEAVE_TYPE_FIELD,
    LEAVE_TYPE_MODEL,
    ODOO_VERSION,
    group_users,
    groups_field,
    legacy_view_mode,
    owl_import_path,
    safe_field_rename,
    setup_access_dropdown,
    tracking,
    user_all_groups,
    user_groups,
)


@tagged('post_install', '-at_install', 'eh_hr', 'eh_hr_compat')
class TestVersionDetection(TransactionCase):

    def test_version_constants_follow_the_running_server(self):
        self.assertEqual(ODOO_VERSION, int(release.version_info[0]),
                         'The shim must read the running major version.')
        self.assertEqual(IS_20_PLUS, ODOO_VERSION >= 20)
        self.assertEqual(IS_19_PLUS, ODOO_VERSION >= 19)
        self.assertEqual(IS_18_PLUS, ODOO_VERSION >= 18)
        self.assertEqual(IS_17_PLUS, ODOO_VERSION >= 17)
        # The ladder is monotonic: a 20 server is also a 19, 18 and 17 server,
        # so reading the flags from newest to oldest never switches off then on.
        ladder = [IS_20_PLUS, IS_19_PLUS, IS_18_PLUS, IS_17_PLUS]
        self.assertEqual(sorted(ladder), ladder,
                         'Version flags must switch on from newest to oldest.')

    def test_contract_model_resolves_to_a_real_model(self):
        self.assertEqual(CONTRACT_MODEL,
                         'hr.version' if IS_19_PLUS else 'hr.contract')
        if 'hr.employee' in self.env:
            self.assertIn(CONTRACT_MODEL, self.env,
                          'With hr installed the contract model must exist.')
            self.assertNotIn(
                'hr.contract' if IS_19_PLUS else 'hr.version', self.env,
                'The superseded contract model must not be in the registry.')

    def test_leave_type_shim_resolves_to_a_real_model_and_field(self):
        self.assertEqual(
            LEAVE_TYPE_MODEL,
            'hr.work.entry.type' if IS_20_PLUS else 'hr.leave.type')
        self.assertEqual(
            LEAVE_TYPE_FIELD,
            'work_entry_type_id' if IS_20_PLUS else 'holiday_status_id')
        if 'hr.leave' in self.env:
            self.assertIn(LEAVE_TYPE_MODEL, self.env)
            self.assertIn(LEAVE_TYPE_FIELD, self.env['hr.leave']._fields,
                          'The leave type field name must exist on hr.leave.')

    def test_field_and_view_shims(self):
        self.assertEqual(tracking(), {'tracking': True})
        self.assertEqual(tracking(False), {'tracking': False})
        modes = 'list,form,kanban'
        self.assertEqual(legacy_view_mode(modes),
                         modes if IS_17_PLUS else 'tree,form,kanban')
        # The view mode string the shim returns has to be one the running
        # server accepts, which an act_window validates on create.
        action = self.env['ir.actions.act_window'].create({
            'name': 'EH compat view mode probe',
            'res_model': 'res.partner',
            'view_mode': legacy_view_mode(modes),
        })
        self.assertEqual(action.view_mode, legacy_view_mode(modes))
        self.assertEqual(owl_import_path(), '@odoo/owl')


@tagged('post_install', '-at_install', 'eh_hr', 'eh_hr_compat')
class TestGroupHelpers(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.internal = cls.env.ref('base.group_user')
        cls.user = cls.env['res.users'].create({
            'name': 'EH compat probe',
            'login': 'eh_compat_probe',
            groups_field(cls.env): [(4, cls.internal.id)],
        })

    def test_groups_field_builds_working_create_vals(self):
        field = groups_field(self.env)
        self.assertIn(field, self.env['res.users']._fields,
                      'The groups field name must exist on res.users.')
        self.assertEqual(field, 'group_ids' if IS_19_PLUS else 'groups_id')
        # The recordset form of the accessor must accept the same argument.
        self.assertEqual(groups_field(self.user), field)
        self.assertIn(self.internal, self.user[field])

    def test_user_groups_reads_the_assigned_groups(self):
        self.assertIn(self.internal, user_groups(self.user))
        extra = self.env['res.groups'].create({'name': 'EH compat extra'})
        self.user.write({groups_field(self.env): [(4, extra.id)]})
        self.assertIn(extra, user_groups(self.user),
                      'A group added after create must be readable.')

    def test_user_all_groups_includes_implied_groups(self):
        # Odoo 19 stopped materialising an implied group into the user's own
        # group_ids, so an authorisation gate that reads the explicit
        # membership refuses a manager who holds an officer group only by
        # implication. user_all_groups is what such a gate must read.
        Groups = self.env['res.groups']
        officer = Groups.create({'name': 'EH compat implied officer'})
        manager = Groups.create({'name': 'EH compat implied manager',
                                 'implied_ids': [(4, officer.id)]})
        self.user.write({groups_field(self.env): [(4, manager.id)]})
        self.assertIn(manager, user_all_groups(self.user))
        self.assertIn(officer, user_all_groups(self.user),
                      'An implied group must be visible to an authorisation '
                      'check.')
        if IS_19_PLUS:
            self.assertNotIn(officer, user_groups(self.user),
                             'From Odoo 19 the explicit membership must NOT '
                             'carry the implied group, which is the whole '
                             'reason this helper exists.')

    def test_group_users_is_the_inverse_relation(self):
        self.assertIn(self.user, group_users(self.internal))
        for group in user_groups(self.user):
            self.assertIn(self.user, group_users(group),
                          'Every group the user holds must list the user.')

    def test_setup_access_dropdown_puts_the_ladder_on_one_selector(self):
        Groups = self.env['res.groups']
        low = Groups.create({'name': 'EH compat level low'})
        high = Groups.create({'name': 'EH compat level high',
                              'implied_ids': [(4, low.id)]})
        for group, name in ((low, 'test_level_low'), (high, 'test_level_high')):
            self.env['ir.model.data'].create({
                'module': 'eh_hr_compat', 'name': name,
                'model': 'res.groups', 'res_id': group.id,
            })
        setup_access_dropdown(self.env, 'EH Compat Access', 42, [
            'eh_hr_compat.test_level_low',
            'eh_hr_compat.test_level_high',
        ])
        if 'privilege_id' in Groups._fields:
            self.assertTrue(low.privilege_id)
            self.assertEqual(low.privilege_id, high.privilege_id,
                             'Both levels must share one selector.')
            self.assertEqual(low.privilege_id.name, 'EH Compat Access')
            self.assertEqual(low.privilege_id.category_id.name, 'HR Platform')
        else:
            self.assertEqual(low.category_id, high.category_id)
            self.assertEqual(low.category_id.name, 'EH Compat Access')

    def test_setup_access_dropdown_ignores_unknown_groups(self):
        # A feature module that is not installed must not break the install
        # hook of one that is: unknown xmlids are dropped and nothing is
        # created for them.
        setup_access_dropdown(self.env, 'EH Compat Missing', 43,
                              ['eh_hr_compat.no_such_group'])
        selector = ('res.groups.privilege' if 'res.groups.privilege' in self.env
                    else 'ir.module.category')
        self.assertFalse(
            self.env[selector].search([('name', '=', 'EH Compat Missing')]),
            'Nothing must be created for a group that does not exist.')


@tagged('post_install', '-at_install', 'eh_hr', 'eh_hr_compat')
class TestSafeFieldRename(TransactionCase):
    """safe_field_rename runs in pre-migrate scripts, where a wrong answer
    silently drops a column of live data, so it is tested against a real
    table on the test cursor."""

    def setUp(self):
        super().setUp()
        self.cr = self.env.cr
        self.cr.execute('CREATE TABLE eh_compat_rename_probe '
                        '(id serial PRIMARY KEY, old_name varchar)')
        self.cr.execute("INSERT INTO eh_compat_rename_probe (old_name) "
                        "VALUES ('kept')")

    def _columns(self):
        self.cr.execute(
            'SELECT column_name FROM information_schema.columns '
            'WHERE table_name = %s', ('eh_compat_rename_probe',))
        return {row[0] for row in self.cr.fetchall()}

    def test_rename_moves_the_column_and_keeps_the_data(self):
        self.assertTrue(safe_field_rename(
            self.cr, 'eh_compat_rename_probe', 'old_name', 'new_name'))
        self.assertEqual(self._columns(), {'id', 'new_name'})
        self.cr.execute('SELECT new_name FROM eh_compat_rename_probe')
        self.assertEqual(self.cr.fetchone()[0], 'kept',
                         'A rename must never lose the stored value.')

    def test_rename_is_idempotent(self):
        safe_field_rename(self.cr, 'eh_compat_rename_probe',
                          'old_name', 'new_name')
        self.assertFalse(
            safe_field_rename(self.cr, 'eh_compat_rename_probe',
                              'old_name', 'new_name'),
            'A second run must report that there was nothing to do.')
        self.assertEqual(self._columns(), {'id', 'new_name'})

    def test_rename_refuses_to_clobber_an_existing_column(self):
        self.cr.execute('ALTER TABLE eh_compat_rename_probe '
                        'ADD COLUMN new_name varchar')
        self.assertFalse(
            safe_field_rename(self.cr, 'eh_compat_rename_probe',
                              'old_name', 'new_name'),
            'Both columns present means the migration already ran.')
        self.assertEqual(self._columns(), {'id', 'old_name', 'new_name'})

    def test_rename_on_an_unknown_table_is_a_no_op(self):
        self.assertFalse(safe_field_rename(
            self.cr, 'eh_compat_no_such_table', 'a', 'b'))
