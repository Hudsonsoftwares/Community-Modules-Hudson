from datetime import date
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountExecutiveSummaryWizard(models.TransientModel):
    """
    Executive Summary — one-page KPI snapshot for management reporting.
    Shows Revenue, Expenses, Net Profit, Cash Position, AR, AP,
    and key ratios (Current Ratio, Quick Ratio, Gross Margin, Net Margin).
    Optionally includes period comparison.
    """
    _name = 'account.executive.summary.wizard'
    _description = 'Executive Summary Report'

    date_from = fields.Date(
        string='Period From',
        required=True,
        default=lambda self: date.today().replace(day=1),
    )
    date_to = fields.Date(
        string='Period To',
        required=True,
        default=lambda self: date.today(),
    )
    compare_date_from = fields.Date(string='Comparison Period From')
    compare_date_to = fields.Date(string='Comparison Period To')
    enable_comparison = fields.Boolean(string='Enable Period Comparison')
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

    def _get_period_sum(self, account_types, df, dt, cid, state):
        """Sum of (debit-credit) for account types in a period."""
        state_clause = "AND aml.parent_state = 'posted'" if state == 'posted' else ''
        query = f"""
            SELECT COALESCE(SUM(aml.debit - aml.credit), 0.0)
            FROM account_move_line aml
            JOIN account_account aa ON aa.id = aml.account_id
            WHERE aa.account_type IN %s
              AND aml.date >= %s AND aml.date <= %s
              AND aml.company_id = %s
              AND aml.display_type NOT IN ('line_section', 'line_note')
              {state_clause}
        """
        self.env.cr.execute(query, (tuple(account_types), df, dt, cid))
        result = self.env.cr.fetchone()
        return result[0] if result else 0.0

    def _get_balance_as_of(self, account_types, as_of, cid, state):
        """Cumulative debit-credit balance up to as_of date."""
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
        self.env.cr.execute(query, (tuple(account_types), as_of, cid))
        result = self.env.cr.fetchone()
        return result[0] if result else 0.0

    def _compute_kpis(self, df, dt, cid, state):
        """Compute all KPIs for a given period."""
        revenue = -self._get_period_sum(['income'], df, dt, cid, state)
        other_income = -self._get_period_sum(['income_other'], df, dt, cid, state)
        cogs = self._get_period_sum(['expense_direct_cost'], df, dt, cid, state)
        opex = self._get_period_sum(['expense', 'expense_depreciation'], df, dt, cid, state)
        total_expenses = cogs + opex
        gross_profit = revenue - cogs
        net_profit = revenue + other_income - total_expenses

        # Balance sheet KPIs as of date_to
        cash = self._get_balance_as_of(['asset_cash'], dt, cid, state)
        ar = self._get_balance_as_of(['asset_receivable'], dt, cid, state)
        current_assets = self._get_balance_as_of(
            ['asset_receivable', 'asset_cash', 'asset_current', 'asset_prepayments'], dt, cid, state
        )
        current_liabilities = -self._get_balance_as_of(
            ['liability_payable', 'liability_credit_card', 'liability_current'], dt, cid, state
        )
        ap = -self._get_balance_as_of(['liability_payable', 'liability_credit_card'], dt, cid, state)

        # Ratios (avoid division by zero)
        current_ratio = (current_assets / current_liabilities) if current_liabilities else 0.0
        quick_ratio = ((cash + ar) / current_liabilities) if current_liabilities else 0.0
        gross_margin = (gross_profit / revenue * 100) if revenue else 0.0
        net_margin = (net_profit / revenue * 100) if revenue else 0.0

        return {
            'revenue': revenue,
            'other_income': other_income,
            'cogs': cogs,
            'opex': opex,
            'total_expenses': total_expenses,
            'gross_profit': gross_profit,
            'net_profit': net_profit,
            'cash': cash,
            'ar': ar,
            'ap': ap,
            'current_assets': current_assets,
            'current_liabilities': current_liabilities,
            'current_ratio': round(current_ratio, 2),
            'quick_ratio': round(quick_ratio, 2),
            'gross_margin': round(gross_margin, 2),
            'net_margin': round(net_margin, 2),
        }

    def _compute_summary_data(self):
        self.ensure_one()
        cid = self.company_id.id
        state = self.target_move
        current = self._compute_kpis(self.date_from, self.date_to, cid, state)

        comparison = None
        if self.enable_comparison and self.compare_date_from and self.compare_date_to:
            comparison = self._compute_kpis(self.compare_date_from, self.compare_date_to, cid, state)

        return {
            'date_from': self.date_from,
            'date_to': self.date_to,
            'company': self.company_id.id,
            'target_move': state,
            'current': current,
            'comparison': comparison,
            'compare_date_from': self.compare_date_from,
            'compare_date_to': self.compare_date_to,
        }

    def action_print_report(self):
        self.ensure_one()
        data = self._compute_summary_data()
        return self.env.ref(
            'hudson_accounting_enhancements.action_report_executive_summary'
        ).report_action(self, data={'form': data})
