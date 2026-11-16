# -*- coding: utf-8 -*-
from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRetentionBonus(TransactionCase):
    """Retention Bonus is a one-time amount (not a monthly salary component): paid in full on the first
    payslip ending on or after Counted From + Retention Period, never twice, forfeited in notice period,
    excluded from the ESIC wage and fully taxable."""

    def setUp(self):
        super().setUp()
        self.company = self.env['res.company'].create({
            'name': 'Retention Co', 'country_id': self.env.ref('base.in').id})
        self.structure = self.env.ref('hudson_payroll_base.structure_base')
        self.employee = self.env['hr.employee'].with_company(self.company).create({
            'name': 'Retention Employee', 'company_id': self.company.id})
        vals = {'wage': 15000.0, 'basic_salary': 15000.0, 'date_version': date(2026, 1, 1),
                'struct_id': self.structure.id, 'contract_date_start': date(2026, 1, 1),
                'retention_bonus': 50000.0, 'retention_period': 3, 'retention_period_unit': 'months'}
        if 'pay_by_attendance' in self.env['hr.version']._fields:
            vals['pay_by_attendance'] = False  # fixed monthly salary, no attendance needed
        self.contract = self.employee.version_id
        self.contract.write(vals)

    def _slip(self, month):
        last_day = {3: 31, 4: 30, 5: 31, 6: 30}[month]
        slip = self.env['hr.payslip'].with_company(self.company).create({
            'name': f'Retention Slip {month}', 'employee_id': self.employee.id, 'company_id': self.company.id,
            'contract_id': self.contract.id, 'struct_id': self.structure.id,
            'date_from': date(2026, month, 1), 'date_to': date(2026, month, last_day)})
        slip.action_compute_sheet()
        return slip

    def _amount(self, slip, code='RETENTION_BONUS'):
        return sum(slip.line_ids.filtered(lambda line: line.code == code).mapped('total'))

    def test_dates_and_breakdown(self):
        # Counted From is empty -> joining date; 3 months -> eligible on 1 April
        self.assertFalse(self.contract.retention_start_date)
        self.assertEqual(self.contract.retention_eligible_date, date(2026, 4, 1))
        self.assertEqual(self.contract.retention_status, 'pending')
        # Years, and an explicit Counted From
        self.contract.write({'retention_start_date': date(2025, 2, 28), 'retention_period': 2,
                             'retention_period_unit': 'years'})
        self.assertEqual(self.contract.retention_eligible_date, date(2027, 2, 28))
        # No period -> never eligible (an amount alone is not paid out)
        self.contract.retention_period = 0
        self.assertFalse(self.contract.retention_eligible_date)
        self.assertEqual(self.contract._hds_retention_amount_due_by(date(2030, 3, 31)), 0.0)
        # Not part of the monthly wage breakdown
        self.assertEqual(self.contract.breakdown_total, 15000.0)
        self.assertTrue(self.contract.breakdown_is_equal)

    def test_paid_once_on_eligibility(self):
        march = self._slip(3)
        self.assertEqual(self._amount(march), 0.0, "paid before the retention period is completed")
        april = self._slip(4)
        self.assertEqual(self._amount(april), 50000.0)
        # Recomputing the paying payslip keeps the amount
        april.action_compute_sheet()
        self.assertEqual(self._amount(april), 50000.0)
        april.write({'state': 'done'})
        self.contract.invalidate_recordset(['retention_status', 'retention_payslip_id'])
        self.assertEqual(self.contract.retention_status, 'validated')
        self.assertEqual(self.contract.retention_payslip_id, april)
        # Shown as Paid only once the payslip itself is paid
        april.write({'state': 'paid'})
        self.contract.invalidate_recordset(['retention_status', 'retention_payslip_id'])
        self.assertEqual(self.contract.retention_status, 'paid')
        may = self._slip(5)
        self.assertEqual(self._amount(may), 0.0, "retention bonus paid twice")
        # Cancelling the paying payslip makes it due again
        april.write({'state': 'cancel'})
        self.contract.invalidate_recordset(['retention_status', 'retention_payslip_id'])
        self.assertEqual(self.contract.retention_status, 'pending')
        may.action_compute_sheet()
        self.assertEqual(self._amount(may), 50000.0)

    def test_new_version_does_not_pay_again(self):
        april = self._slip(4)
        april.write({'state': 'done'})
        new_version = self.contract.copy({'date_version': date(2026, 5, 1)})
        self.assertEqual(new_version.retention_bonus, 50000.0)
        self.assertEqual(new_version.retention_status, 'validated')
        self.assertEqual(new_version._hds_retention_amount_due_by(date(2027, 3, 31)), 0.0)

    def test_forfeited_in_notice_period(self):
        # Resignation registered: leaving after the eligible date, so in notice period on the April payslip
        self.env['hr.employee.departure'].create({'employee_id': self.employee.id, 'dismissal_date': date(2026, 6, 30)})
        self.assertTrue(self.employee.departure_date)
        self.contract.invalidate_recordset(['retention_status', 'retention_payslip_id'])
        self.assertEqual(self.contract.retention_status, 'forfeited')
        self.assertEqual(self._amount(self._slip(4)), 0.0)
        self.assertEqual(self.contract._hds_retention_amount_due_by(date(2027, 3, 31)), 0.0)

    def test_excluded_from_esic_wage(self):
        self.company.hds_in_esic_applicable = True
        april = self._slip(4)
        self.assertEqual(self._amount(april), 50000.0)
        gross = self._amount(april, 'GROSS')
        self.assertGreaterEqual(gross, 65000.0)
        esic_wage = self._amount(april, 'ESIC_WAGE')
        self.assertEqual(esic_wage, gross - 50000.0)

    def test_tds_counts_it_once_in_its_year(self):
        # Due in FY 2026-27 (eligible 1 April 2026), still unpaid -> counted once, not monthly
        self.assertEqual(self.contract._hds_retention_amount_due_by(date(2027, 3, 31)), 50000.0)
        # Not due in a year ending before the eligible date
        self.assertEqual(self.contract._hds_retention_amount_due_by(date(2026, 3, 31)), 0.0)
        # Paid -> nothing more to project
        self._slip(4).write({'state': 'done'})
        self.assertEqual(self.contract._hds_retention_amount_due_by(date(2027, 3, 31)), 0.0)
