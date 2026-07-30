from datetime import date, timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountCashFlowWizard(models.TransientModel):
    """
    Cash Flow Statement wizard using the Indirect Method.

    Indirect Method structure:
    A. Operating Activities
       1. Net Profit for the period (from P&L accounts)
       2. Add back: Depreciation & Amortisation (non-cash expense)
       3. Changes in Working Capital:
          - (Increase)/Decrease in Trade Receivables
          - (Increase)/Decrease in Inventories & Prepayments
          - (Increase)/Decrease in Other Current Assets
          - Increase/(Decrease) in Trade Payables
          - Increase/(Decrease) in Other Current Liabilities
    B. Investing Activities
       - Net purchase of Fixed Assets (increase in fixed asset accounts)
       - Net proceeds from asset disposals
    C. Financing Activities
       - Net proceeds from long-term borrowings
       - Changes in equity (capital injections / dividends)
    D. Net Change in Cash = A + B + C
    E. Opening Cash Balance
    F. Closing Cash Balance = D + E
    """
    _name = 'account.cash.flow.wizard'
    _description = 'Cash Flow Statement (Indirect Method)'

    date_from = fields.Date(
        string='Date From',
        required=True,
        default=lambda self: date.today().replace(day=1, month=1),
    )
    date_to = fields.Date(
        string='Date To',
        required=True,
        default=lambda self: date.today(),
    )
    target_move = fields.Selection(
        [('posted', 'All Posted Entries'), ('all', 'All Entries')],
        string='Target Moves',
        required=True,
        default='posted',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )

    def _get_balance_at_date(self, account_types, at_date, company_id, state='posted'):
        """
        Returns the cumulative debit-credit balance for accounts of given types
        up to (and including) at_date.
        Positive = net debit balance (assets/expenses)
        Negative = net credit balance (liabilities/income/equity)
        """
        type_list = tuple(account_types) if len(account_types) > 1 else f"('{account_types[0]}')"
        state_clause = "AND aml.parent_state = 'posted'" if state == 'posted' else ''
        query = f"""
            SELECT COALESCE(SUM(aml.debit - aml.credit), 0.0)
            FROM account_move_line aml
            JOIN account_account aa ON aa.id = aml.account_id
            WHERE aa.account_type IN %s
              AND aml.date <= %s
              AND aml.company_id = %s
              AND aml.display_type NOT IN ('line_section', 'line_note')
              {state_clause}
        """
        self.env.cr.execute(query, (tuple(account_types), at_date, company_id))
        result = self.env.cr.fetchone()
        return result[0] if result else 0.0

    def _get_period_movement(self, account_types, date_from, date_to, company_id, state='posted'):
        """
        Returns the net debit-credit movement for accounts of given types
        within the period [date_from, date_to].
        """
        state_clause = "AND aml.parent_state = 'posted'" if state == 'posted' else ''
        query = f"""
            SELECT COALESCE(SUM(aml.debit - aml.credit), 0.0)
            FROM account_move_line aml
            JOIN account_account aa ON aa.id = aml.account_id
            WHERE aa.account_type IN %s
              AND aml.date >= %s
              AND aml.date <= %s
              AND aml.company_id = %s
              AND aml.display_type NOT IN ('line_section', 'line_note')
              {state_clause}
        """
        self.env.cr.execute(query, (tuple(account_types), date_from, date_to, company_id))
        result = self.env.cr.fetchone()
        return result[0] if result else 0.0

    def _compute_cash_flow_data(self):
        """
        Compute all cash flow sections and return a structured dictionary.
        """
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('Date From must be before Date To.'))

        company_id = self.company_id.id
        date_from = self.date_from
        date_to = self.date_to
        state = self.target_move

        # Date before period start (for opening balances)
        date_before = date_from - timedelta(days=1)

        # ────────────────────────────────────────────────────────
        # A. OPERATING ACTIVITIES (Indirect Method)
        # ────────────────────────────────────────────────────────

        # 1. Net Profit
        # P&L accounts: income (credit normal) and expenses (debit normal)
        # Net Profit = SUM(credit - debit) for all P&L accounts in period
        # = SUM(-(debit - credit)) = -period_movement for P&L accounts
        pl_types = ['income', 'income_other', 'expense', 'expense_depreciation', 'expense_direct_cost']
        pl_movement = self._get_period_movement(pl_types, date_from, date_to, company_id, state)
        net_profit = -pl_movement  # flip sign: credit excess on income = positive profit

        # 2. Add back Depreciation (non-cash expense)
        dep_movement = self._get_period_movement(
            ['expense_depreciation'], date_from, date_to, company_id, state
        )
        depreciation = dep_movement  # debit-normal: positive = depreciation charge

        # 3. Working Capital Changes
        # For assets: increase = cash outflow = negative CF impact
        # Change = (balance_end - balance_start)
        # CF impact for assets = -(balance_end - balance_start)
        # CF impact for liabilities = (balance_end - balance_start) [increase = more credit = positive CF]

        # Trade Receivables
        ar_start = self._get_balance_at_date(['asset_receivable'], date_before, company_id, state)
        ar_end = self._get_balance_at_date(['asset_receivable'], date_to, company_id, state)
        ar_change = -(ar_end - ar_start)  # increase in AR = cash outflow

        # Inventories & Prepayments
        inv_start = self._get_balance_at_date(['asset_current', 'asset_prepayments'], date_before, company_id, state)
        inv_end = self._get_balance_at_date(['asset_current', 'asset_prepayments'], date_to, company_id, state)
        inv_change = -(inv_end - inv_start)

        # Other Current Assets (non-current excluding fixed)
        oca_start = self._get_balance_at_date(['asset_non_current'], date_before, company_id, state)
        oca_end = self._get_balance_at_date(['asset_non_current'], date_to, company_id, state)
        oca_change = -(oca_end - oca_start)

        # Trade Payables
        ap_start = self._get_balance_at_date(['liability_payable', 'liability_credit_card'], date_before, company_id, state)
        ap_end = self._get_balance_at_date(['liability_payable', 'liability_credit_card'], date_to, company_id, state)
        ap_change = -(ap_end - ap_start)  # liabilities: debit-credit is negative, increase (more negative) = cash inflow

        # Other Current Liabilities
        ocl_start = self._get_balance_at_date(['liability_current'], date_before, company_id, state)
        ocl_end = self._get_balance_at_date(['liability_current'], date_to, company_id, state)
        ocl_change = -(ocl_end - ocl_start)

        working_capital_change = ar_change + inv_change + oca_change + ap_change + ocl_change

        operating_total = net_profit + depreciation + working_capital_change

        # ────────────────────────────────────────────────────────
        # B. INVESTING ACTIVITIES
        # ────────────────────────────────────────────────────────
        # In Odoo, asset_fixed account type captures BOTH:
        #   - Fixed asset cost accounts (debit-normal, debit when purchased)
        #   - Accumulated depreciation accounts (credit-normal, credited when depreciation runs)
        # So: balance(asset_fixed) = Gross Cost - Accumulated Depreciation = Net Book Value
        #
        # Net Book Value change in period:
        #   fa_end - fa_start = Purchases - Depreciation_charged
        #
        # Cash actually paid for assets (gross capex):
        #   Purchases = (fa_end - fa_start) + Depreciation_charged
        #   Cash outflow for assets = -(fa_end - fa_start) - depreciation
        #
        # Note: depreciation appears as POSITIVE in operating (add-back to net profit)
        # and NEGATIVE in investing (to convert net book value change to gross cash spent).
        # This does NOT double-count: the two effects cancel, correctly showing
        # that depreciation is non-cash (no net effect on total cash position).

        fa_start = self._get_balance_at_date(['asset_fixed'], date_before, company_id, state)
        fa_end = self._get_balance_at_date(['asset_fixed'], date_to, company_id, state)
        # Net book value change (could be positive if purchases > depreciation)
        fa_net_change = fa_end - fa_start
        # Gross cash spent on assets = net change + depreciation removed from book value
        gross_capex = -(fa_net_change + depreciation)  # negative = cash outflow

        investing_total = gross_capex

        # ────────────────────────────────────────────────────────
        # C. FINANCING ACTIVITIES
        # ────────────────────────────────────────────────────────
        # Long-term liabilities: increase = borrowing = cash inflow
        ltl_start = self._get_balance_at_date(['liability_non_current'], date_before, company_id, state)
        ltl_end = self._get_balance_at_date(['liability_non_current'], date_to, company_id, state)
        borrowings = -(ltl_end - ltl_start)  # liabilities: debit-credit is negative; increase (more negative) = inflow

        # Equity changes (capital injection/dividends)
        eq_start = self._get_balance_at_date(['equity', 'equity_unaffected'], date_before, company_id, state)
        eq_end = self._get_balance_at_date(['equity', 'equity_unaffected'], date_to, company_id, state)
        equity_change = -(eq_end - eq_start)  # equity: credit normal; increase = inflow

        financing_total = borrowings + equity_change

        # ────────────────────────────────────────────────────────
        # D. CASH POSITION
        # ────────────────────────────────────────────────────────
        cash_types = ['asset_cash']
        opening_cash = self._get_balance_at_date(cash_types, date_before, company_id, state)
        closing_cash = self._get_balance_at_date(cash_types, date_to, company_id, state)
        net_change = operating_total + investing_total + financing_total

        return {
            'date_from': date_from,
            'date_to': date_to,
            'company': self.company_id.id,
            'target_move': self.target_move,
            # Operating
            'net_profit': net_profit,
            'depreciation': depreciation,
            'ar_change': ar_change,
            'inv_change': inv_change,
            'oca_change': oca_change,
            'ap_change': ap_change,
            'ocl_change': ocl_change,
            'working_capital_change': working_capital_change,
            'operating_total': operating_total,
            # Investing
            'gross_capex': gross_capex,
            'investing_total': investing_total,
            # Financing
            'borrowings': borrowings,
            'equity_change': equity_change,
            'financing_total': financing_total,
            # Cash
            'opening_cash': opening_cash,
            'net_change': net_change,
            'closing_cash': closing_cash,
        }

    def action_print_report(self):
        self.ensure_one()
        data = self._compute_cash_flow_data()
        return self.env.ref(
            'hudson_accounting_enhancements.action_report_cash_flow'
        ).report_action(self, data={'form': data})
