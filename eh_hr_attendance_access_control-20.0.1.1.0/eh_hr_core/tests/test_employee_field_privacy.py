# -*- coding: utf-8 -*-
"""Privacy of the fields the ERP Heritage modules add to hr.employee.

In Odoo 20 only two groups may read hr.employee: HR users (hr.group_hr_user)
and administrators (base.group_system, read only). Everyone else is served the
public profile: fetch and search_fetch copy the hr.employee.public values and
refuse any other field. The fields are discovered from the registry, so this
holds over whatever modules are installed with this one (on a full install,
the whole suite):

* a stored field is either restricted to a group a plain internal user does not
  hold, or declared on hr.employee.public. Otherwise it joins the prefetch of
  any attribute read such a user makes, and hr.employee refuses the whole read:
  a point of sale cashier could not even read a colleague's name;
* such a user still reads the public profile of another employee;
* no restricted value ever reaches that user: read, search_read and
  web_search_read either raise AccessError or return nothing, and every
  grouped read raises AccessError. A grouped read runs on the superuser query
  hr.employee._search builds for people outside HR, where neither field
  groups nor the public profile are checked, so only the guard the ERP
  Heritage modules carry keeps a private value from coming back as a group
  key or an aggregate;
* an administrator outside HR, who may read hr.employee, is refused every
  field restricted with groups=, on a read and on every grouped read;
* a many2many restricted with groups= is refused as a group by, core's own
  included, to that administrator and to anyone grouping another model by it
  through a many2one path. Odoo 20 builds a many2many group by without the
  field access check every other grouped term goes through.

The payroll engines read the employee configuration their formulas need as
superuser, so a payroll officer of the HR platform who is not an HR user still
computes a payslip; that is proven at the end, for whichever of the payroll
localizations is installed.
"""
from datetime import date

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user, tagged


def _eh_modules(field):
    return [module for module in field._modules if module.startswith('eh_')]


def _groupby_spec(name, field):
    return name + (':year' if field.type in ('date', 'datetime') else '')


def _grouped_reads(employees, field):
    """(label, call) for every public way to read ``field`` of hr.employee
    grouped: each call returns the rows it got back."""
    name = field.name
    groupby = _groupby_spec(name, field)
    return [
        ('formatted_read_group groupby', lambda: employees.formatted_read_group(
            [], [groupby], ['__count'])),
        ('formatted_read_group array_agg', lambda: employees.formatted_read_group(
            [], [], ['%s:array_agg' % name])),
        ('formatted_read_group having', lambda: employees.formatted_read_group(
            [], ['company_id'], ['__count'],
            having=[('%s:count_distinct' % name, '>', 0)])),
        ('formatted_read_group order', lambda: employees.formatted_read_group(
            [], ['company_id'], ['__count'],
            order='%s:count_distinct desc' % name)),
        ('formatted_read_group many2one path', lambda: employees.formatted_read_group(
            [], ['parent_id.%s' % groupby], ['__count'])),
        ('formatted_read_grouping_sets', lambda: [
            group for groups in employees.formatted_read_grouping_sets(
                [], [['company_id'], [groupby]], ['__count'])
            for group in groups]),
        # The Odoo 20 public tuple API, an RPC entry point in its own right.
        ('read_group', lambda: employees.read_group(  # odoo20-sweep: ok Odoo 20 signature, proven refused
            [], [groupby], ['__count'])),
        ('web_read_group', lambda: employees.web_read_group(
            [], [groupby], ['__count'])['groups']),
    ]


@tagged('post_install', '-at_install', 'eh_hr', 'eh_hr_security')
class TestEmployeeFieldPrivacy(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = ['base.group_user']
        if cls.env.ref('point_of_sale.group_pos_user', raise_if_not_found=False):
            groups.append('point_of_sale.group_pos_user')
        cls.user = new_test_user(
            cls.env, login='eh_privacy_cashier', groups=','.join(groups),
            name='Privacy Cashier')
        cls.admin_outside_hr = new_test_user(
            cls.env, login='eh_privacy_admin',
            groups='base.group_user,base.group_system',
            name='Privacy Administrator')
        cls.Employee = cls.env['hr.employee']
        public_fields = cls.env['hr.employee.public']._fields
        cls.tag = cls.env['hr.employee.category'].create({
            'name': 'EH-PRIVATE-tag'})
        cls.colleague = cls.Employee.create({
            'name': 'Privacy Colleague', 'company_id': cls.env.company.id,
            'category_ids': [(6, 0, cls.tag.ids)]})
        # The colleague manages a department, which anyone may read: the way
        # to reach the colleague's fields from another model.
        cls.department = cls.env['hr.department'].create({
            'name': 'Privacy Department', 'manager_id': cls.colleague.id})
        cls.eh_fields = [
            field for field in cls.Employee._fields.values() if _eh_modules(field)]
        as_user = cls.Employee.with_user(cls.user)
        # Restricted for a plain internal user: off the public profile, or
        # behind a group that user does not hold.
        cls.private_fields = [
            field for field in cls.eh_fields
            if field.name not in public_fields
            or not as_user.has_field_access(field, 'read')
        ]
        as_admin = cls.Employee.with_user(cls.admin_outside_hr)
        cls.grouped_fields = [
            field for field in cls.eh_fields
            if field.groups and not as_admin.has_field_access(field, 'read')
        ]
        # Every stored many2many of hr.employee restricted with groups=,
        # core's own included (a computed one cannot be grouped at all).
        cls.restricted_many2many = [
            field for field in cls.Employee._fields.values()
            if field.type == 'many2many' and field.store and field.groups
            and not as_admin.has_field_access(field, 'read')
        ]
        # A value in every private text column, so a leak shows the value it
        # leaked; the assertions below refuse any row, whatever it holds.
        for field in cls.private_fields:
            if field.store and field.column_type and field.type in ('char', 'text'):
                try:
                    with cls.env.cr.savepoint():
                        cls.colleague.write({field.name: 'EH-PRIVATE-%s' % field.name})
                except Exception:  # noqa: BLE001 a field that refuses a free text value keeps its own
                    pass
        cls.env.flush_all()

    def _nothing_comes_back(self, call, what):
        """The call is refused, or it returns no row at all: never a value."""
        try:
            rows = call()
        except AccessError:
            return
        self.assertFalse(
            rows, '%s returned %r to a user outside HR' % (what, rows))

    def _runs_as_superuser(self, call):
        """Whether core can run this read at all: a one2many or a non stored
        computed field cannot be grouped or aggregated, and some aggregates do
        not apply to every column type, so asking a user for them proves
        nothing."""
        try:
            with self.env.cr.savepoint():
                call()
        except Exception:  # noqa: BLE001 whatever core refuses is not a read
            return False
        return True

    def _grouped_reads_to_prove(self, field, employees):
        """The grouped reads of ``field`` core can run, for ``employees``.

        Only a field without a column of its own may be one core cannot group,
        so the loop never skips a stored column silently."""
        superuser = self.Employee.sudo()
        runnable = []
        for (label, call), (_label, sudo_call) in zip(
                _grouped_reads(employees, field), _grouped_reads(superuser, field)):
            if self._runs_as_superuser(sudo_call):
                runnable.append((label, call))
            elif label == 'formatted_read_group groupby':
                self.assertFalse(
                    field.store and field.column_type,
                    '%s is a stored column core should group' % field.name)
        return runnable

    def test_the_two_roles_hold_no_hr_rights(self):
        self.assertFalse(self.user.has_group('hr.group_hr_user'))
        self.assertFalse(self.Employee.with_user(self.user).browse().has_access('read'))
        self.assertTrue(self.admin_outside_hr.has_group('base.group_system'))
        self.assertFalse(self.admin_outside_hr.has_group('hr.group_hr_user'))
        self.assertTrue(
            self.Employee.with_user(self.admin_outside_hr).browse().has_access('read'))

    def test_stored_employee_fields_are_restricted_or_public(self):
        employees = self.Employee.with_user(self.user)
        public_fields = self.env['hr.employee.public']._fields
        offenders = sorted(
            '%s (%s)' % (field.name, ', '.join(_eh_modules(field)))
            for field in self.eh_fields
            if field.store and (field.column_type or field.type == 'many2many')
            and field.name not in public_fields
            and employees.has_field_access(field, 'read')
        )
        self.assertFalse(
            offenders,
            "These stored hr.employee fields are readable by a plain internal "
            "user but are not on hr.employee.public. Restrict them "
            "(groups='hr.group_hr_user', as core does) or declare them on the "
            "public profile: %s" % ', '.join(offenders))

    def test_plain_user_reads_the_public_profile_of_a_colleague(self):
        # The point of sale case: the cashier reads another employee's name
        # and company by attribute, which goes through the prefetch, with a
        # cache that holds nothing yet.
        self.env.flush_all()
        self.env.invalidate_all()
        colleague = self.colleague.with_user(self.user)
        self.assertEqual(colleague.name, 'Privacy Colleague')
        self.assertEqual(colleague.company_id, self.env.company)
        self.env.invalidate_all()
        [values] = colleague.read(['name', 'company_id'])
        self.assertEqual(values['name'], 'Privacy Colleague')
        self.assertEqual(values['company_id'][0], self.env.company.id)

    def test_public_fields_still_group_for_a_plain_user(self):
        # The refusals below come from the fields asked for: the same user
        # does get the colleague back when grouping by what is public.
        employees = self.Employee.with_user(self.user)
        groups = employees.formatted_read_group(
            [('id', '=', self.colleague.id)],
            ['company_id', 'parent_id.name'], ['id:count_distinct'],
            order='company_id')
        self.assertEqual(
            [(group['company_id'][0], group['id:count_distinct']) for group in groups],
            [(self.env.company.id, 1)])

    def test_no_private_value_reaches_a_plain_user_on_read(self):
        colleague = self.colleague.with_user(self.user)
        employees = self.Employee.with_user(self.user)
        domain = [('id', '=', self.colleague.id)]
        for field in self.private_fields:
            name = field.name
            with self.subTest(field=name):
                self.env.invalidate_all()
                self._nothing_comes_back(
                    lambda: colleague.read([name]), 'read(%s)' % name)
                self._nothing_comes_back(
                    lambda: employees.search_read(domain, [name]),
                    'search_read(%s)' % name)
                self._nothing_comes_back(
                    lambda: employees.web_search_read(domain, {name: {}})['records'],
                    'web_search_read(%s)' % name)

    def test_no_private_value_reaches_a_plain_user_on_grouped_read(self):
        employees = self.Employee.with_user(self.user)
        proven = 0
        for field in self.private_fields:
            for label, call in self._grouped_reads_to_prove(field, employees):
                with self.subTest(field=field.name, read=label):
                    with self.assertRaises(AccessError):
                        call()
                    proven += 1
        stored = [field for field in self.private_fields
                  if field.store and field.column_type]
        if stored:
            self.assertGreater(proven, 0, 'a stored private column was grouped')

    def test_admin_outside_hr_is_refused_restricted_fields_on_read(self):
        colleague = self.colleague.with_user(self.admin_outside_hr)
        employees = self.Employee.with_user(self.admin_outside_hr)
        domain = [('id', '=', self.colleague.id)]
        for field in self.grouped_fields:
            name = field.name
            with self.subTest(field=name):
                self.env.invalidate_all()
                with self.assertRaises(AccessError):
                    colleague.read([name])
                with self.assertRaises(AccessError):
                    employees.search_read(domain, [name])

    def test_admin_outside_hr_is_refused_restricted_fields_on_grouped_read(self):
        employees = self.Employee.with_user(self.admin_outside_hr)
        for field in self.grouped_fields:
            for label, call in self._grouped_reads_to_prove(field, employees):
                with self.subTest(field=field.name, read=label):
                    with self.assertRaises(AccessError):
                        call()

    def test_admin_outside_hr_is_refused_restricted_many2many_group_by(self):
        # Core's employee tags are always there, and the administrator may
        # read the tag model, so a leak shows the tag instead of an error.
        self.assertIn(self.Employee._fields['category_ids'], self.restricted_many2many)
        self.assertTrue(
            self.env['hr.employee.category'].with_user(self.admin_outside_hr)
            .browse().has_access('read'))
        employees = self.Employee.with_user(self.admin_outside_hr)
        for field in self.restricted_many2many:
            reads = self._grouped_reads_to_prove(field, employees)
            self.assertTrue(reads, '%s cannot be grouped at all' % field.name)
            for label, call in reads:
                with self.subTest(field=field.name, read=label):
                    with self.assertRaises(AccessError):
                        call()

    def test_restricted_many2many_is_refused_through_another_model(self):
        # hr.department is readable by every internal user and its manager is
        # an employee: grouping departments by the manager's tags must not
        # hand out what grouping the employees refuses.
        for user in (self.user, self.admin_outside_hr):
            departments = self.env['hr.department'].with_user(user)
            self.assertTrue(departments.browse().has_access('read'))
            for field in self.restricted_many2many:
                spec = 'manager_id.%s' % field.name
                with self.subTest(user=user.login, groupby=spec):
                    with self.assertRaises(AccessError):
                        departments.formatted_read_group(
                            [('id', '=', self.department.id)], [spec], ['__count'])


@tagged('post_install', '-at_install', 'eh_hr', 'eh_hr_security')
class TestPayslipReadsEmployeeConfiguration(TransactionCase):
    """A payroll officer of the HR platform computes payslips without being an
    HR user, while the tax settings the formulas need sit on hr.employee,
    restricted to HR users."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.officer = new_test_user(
            cls.env, login='eh_privacy_payroll_officer',
            groups='base.group_user,eh_hr_core.group_hr_officer',
            name='Privacy Payroll Officer')

    def _compute_as_officer(self, structure_xmlid, **employee_vals):
        structure = self.env.ref(structure_xmlid, raise_if_not_found=False)
        if structure is None:
            self.skipTest('%s is not installed' % structure_xmlid.split('.')[0])
        employee = self.env['hr.employee'].create(
            dict(employee_vals, name='Privacy Payee'))
        slip = self.env['eh.hr.payslip'].create({
            'employee_id': employee.id,
            'structure_id': structure.id,
            'date_from': date(2026, 1, 1), 'date_to': date(2026, 1, 31),
            'basic_wage': 5000.0,
        })
        self.assertFalse(self.officer.has_group('hr.group_hr_user'))
        self.env.flush_all()
        self.env.invalidate_all()
        slip.with_user(self.officer).action_compute()
        return {line.code: line.total for line in slip.line_ids}

    def test_officer_computes_au_payslip_on_the_employee_payg_scale(self):
        if 'eh.hr.payg.bracket' not in self.env:
            self.skipTest('eh_hr_payroll_au is not installed')
        Bracket = self.env['eh.hr.payg.bracket']
        Bracket.create({'scale': '1', 'weekly_upto': 99999999.0,
                        'coeff_a': 0.20, 'coeff_b': 50.0})
        lines = self._compute_as_officer(
            'eh_hr_payroll_au.structure_au_standard', eh_payg_scale='1')
        expected = Bracket.compute_period_payg(5000.0, 12, '1')
        self.assertNotAlmostEqual(
            expected, Bracket.compute_period_payg(5000.0, 12, '2'), places=2)
        self.assertAlmostEqual(lines['PAYG'], expected, places=2)

    def test_officer_computes_uk_payslip_on_the_employee_ni_category(self):
        if 'eh.hr.ni.category' not in self.env:
            self.skipTest('eh_hr_payroll_uk is not installed')
        standard = self._compute_as_officer(
            'eh_hr_payroll_uk.structure_uk_standard', eh_ni_category='A')
        pension_age = self._compute_as_officer(
            'eh_hr_payroll_uk.structure_uk_standard', eh_ni_category='C')
        # Category C (over State Pension age) pays no employee NI.
        self.assertGreater(standard['NI_EE'], 0.0)
        self.assertEqual(pension_age['NI_EE'], 0.0)
