# -*- coding: utf-8 -*-
from datetime import date
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.exceptions import UserError, ValidationError, AccessError


@tagged('post_install', '-at_install', 'dental_payment_summary')
class TestDentalPaymentSummary(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        common = {'company_id': cls.company.id, 'company_ids': [cls.company.id]}

        cls.receptionist = new_test_user(
            cls.env, login='rec_user',
            groups='base.group_user,dental_base.group_dental_receptionist',
            **common
        )
        cls.manager = new_test_user(
            cls.env, login='mgr_user',
            groups='base.group_user,dental_base.group_dental_manager',
            **common
        )

        cls.patient = cls.env['res.partner'].create({
            'name': 'John Doe Patient',
            'is_dental_patient': True,
            'dental_patient_id': 'DP-0099',
        })

        # Fetch or create cash and bank journals
        cls.cash_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'cash'),
        ], limit=1)
        if not cls.cash_journal:
            cls.cash_journal = cls.env['account.journal'].create({
                'name': 'Front Desk Cash',
                'type': 'cash',
                'code': 'CSH01',
                'company_id': cls.company.id,
            })

        cls.bank_journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.company.id),
            ('type', '=', 'bank'),
        ], limit=1)
        if not cls.bank_journal:
            cls.bank_journal = cls.env['account.journal'].create({
                'name': 'Card / POS Bank',
                'type': 'bank',
                'code': 'BNK01',
                'company_id': cls.company.id,
            })

    def test_payment_summary_creation_and_reconciliation(self):
        """Test daily summary generation, transaction aggregation, and cash reconciliation."""
        today = date.today()

        # Create sample payment summary
        summary = self.env['dental.payment.summary'].with_user(self.receptionist).create({
            'date': today,
            'company_id': self.company.id,
        })
        self.assertTrue(summary.name and summary.name != 'New')
        self.assertEqual(summary.state, 'draft')
        self.assertTrue(len(summary.journal_line_ids) >= 1)
        self.assertTrue(len(summary.denomination_ids) >= 1)

        # Set physical cash count via cash journal line
        cash_line = summary.journal_line_ids.filtered(lambda j: j.journal_type == 'cash')[:1]
        self.assertTrue(cash_line)
        cash_line.amount_counted = 1500.0
        summary.invalidate_recordset()

        self.assertEqual(summary.total_cash_counted, 1500.0)

    def test_denomination_calculation(self):
        """Entering cash denominations should automatically compute counted cash."""
        summary = self.env['dental.payment.summary'].with_user(self.receptionist).create({
            'date': date.today(),
            'company_id': self.company.id,
        })

        d500 = summary.denomination_ids.filtered(lambda d: d.denomination_value == 500.0)[:1]
        d200 = summary.denomination_ids.filtered(lambda d: d.denomination_value == 200.0)[:1]

        if d500:
            d500.count = 4   # 4 x 500 = 2000
        if d200:
            d200.count = 3   # 3 x 200 = 600

        summary.invalidate_recordset()
        expected_counted = (4 * 500.0 if d500 else 0) + (3 * 200.0 if d200 else 0)
        self.assertEqual(summary.total_cash_counted, expected_counted)

    def test_closing_discrepancy_validation(self):
        """Closing with a cash difference requires an explanation note."""
        summary = self.env['dental.payment.summary'].with_user(self.receptionist).create({
            'date': date.today(),
            'company_id': self.company.id,
        })
        # Set counted cash to non-zero when expected is 0 => discrepancy
        cash_line = summary.journal_line_ids.filtered(lambda j: j.journal_type == 'cash')[:1]
        cash_line.amount_counted = 50.0
        summary.invalidate_recordset()

        # Attempt to close without note -> should raise ValidationError
        summary.note = False
        with self.assertRaises(ValidationError):
            summary.action_close()

        # Add discrepancy note and close -> should succeed
        summary.note = "50 discrepancy due to petty cash change."
        summary.action_close()
        self.assertEqual(summary.state, 'closed')
        self.assertEqual(summary.closing_user_id, self.receptionist)
        self.assertTrue(summary.closing_date)

    def test_reopen_permissions(self):
        """Only clinic managers/admins can reopen a closed summary."""
        summary = self.env['dental.payment.summary'].with_user(self.receptionist).create({
            'date': date.today(),
            'company_id': self.company.id,
        })
        cash_line = summary.journal_line_ids.filtered(lambda j: j.journal_type == 'cash')[:1]
        cash_line.amount_counted = 0.0
        summary.note = "Reconciled with zero balance."
        summary.action_close()
        self.assertEqual(summary.state, 'closed')

        # Receptionist trying to reopen -> AccessError
        with self.assertRaises(AccessError):
            summary.with_user(self.receptionist).action_reopen()

        # Manager reopening -> success
        summary.with_user(self.manager).action_reopen()
        self.assertEqual(summary.state, 'draft')
        self.assertFalse(summary.closing_user_id)

    def test_action_open_or_create_today(self):
        """The helper method opens an existing summary or creates one for today."""
        action = self.env['dental.payment.summary'].with_user(self.receptionist).action_open_or_create_today()
        self.assertEqual(action.get('res_model'), 'dental.payment.summary')
        self.assertTrue(action.get('res_id'))
        self.assertEqual(action.get('views'), [(False, 'form')])

        # Calling it again returns the same record
        action2 = self.env['dental.payment.summary'].with_user(self.receptionist).action_open_or_create_today()
        self.assertEqual(action['res_id'], action2['res_id'])

