from datetime import date
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountUnrealizedCurrencyWizard(models.TransientModel):
    """
    Unrealized Currency Gains/Losses Report.

    For each open receivable/payable in a foreign currency, computes:
    - Original amount in company currency (at transaction date rate)
    - Current value in company currency (at today's/selected rate)
    - Unrealized Gain or Loss = Current Value - Original Value

    Positive = Unrealized Gain, Negative = Unrealized Loss.

    Uses: account.move.line with reconciled=False on receivable/payable accounts
    where currency_id != company currency_id.
    """
    _name = 'account.unrealized.currency.wizard'
    _description = 'Unrealized Currency Gains/Losses'

    as_of_date = fields.Date(
        string='As Of Date',
        required=True,
        default=lambda self: date.today(),
        help='Compute unrealized gains/losses using exchange rates as of this date.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )

    def _get_currency_rate(self, currency, as_of_date, company):
        """Get the exchange rate for a currency as of a given date."""
        if currency == company.currency_id:
            return 1.0
        rate_record = self.env['res.currency.rate'].search([
            ('currency_id', '=', currency.id),
            ('name', '<=', as_of_date),
            ('company_id', '=', company.id),
        ], order='name desc', limit=1)
        if rate_record and rate_record.rate:
            # Odoo rate: amount of foreign per 1 company_currency
            # To get company_currency per 1 foreign: 1 / rate
            return 1.0 / rate_record.rate
        return 1.0

    def _compute_unrealized_data(self):
        self.ensure_one()
        company = self.company_id
        as_of = self.as_of_date

        # Get all unreconciled move lines in foreign currencies on AR/AP accounts
        lines = self.env['account.move.line'].search([
            ('company_id', '=', company.id),
            ('account_id.account_type', 'in', ['asset_receivable', 'liability_payable']),
            ('reconciled', '=', False),
            ('parent_state', '=', 'posted'),
            ('currency_id', '!=', company.currency_id.id),
            ('currency_id', '!=', False),
            ('date', '<=', as_of),
        ])

        # Group by currency
        by_currency = {}
        for line in lines:
            curr = line.currency_id
            if curr not in by_currency:
                by_currency[curr] = {
                    'currency': curr,
                    'lines': [],
                }
            by_currency[curr]['lines'].append(line)

        results = []
        total_unrealized = 0.0

        for curr, group in by_currency.items():
            # Get current rate (1 foreign = X company_currency)
            current_rate = self._get_currency_rate(curr, as_of, company)

            currency_result = {
                'currency_name': curr.name,
                'currency_symbol': curr.symbol,
                'items': [],
                'total_original': 0.0,
                'total_current': 0.0,
                'total_gain_loss': 0.0,
            }

            for line in group['lines']:
                # Original amount in company currency (as recorded at transaction)
                original_company = line.debit - line.credit  # positive for AR, negative for AP

                # Amount in foreign currency
                amount_foreign = line.amount_currency  # signed

                # Current value in company currency at today's rate
                current_company = amount_foreign * current_rate

                # Unrealized gain/loss
                unrealized = current_company - original_company

                currency_result['items'].append({
                    'partner': line.partner_id.name or '',
                    'date': line.date,
                    'ref': line.move_id.name or line.name or '',
                    'account': f"{line.account_id.code} {line.account_id.name}",
                    'amount_foreign': amount_foreign,
                    'original_company': original_company,
                    'current_rate': round(current_rate, 6),
                    'current_company': current_company,
                    'unrealized': unrealized,
                })

                currency_result['total_original'] += original_company
                currency_result['total_current'] += current_company
                currency_result['total_gain_loss'] += unrealized

            total_unrealized += currency_result['total_gain_loss']
            results.append(currency_result)

        return {
            'as_of_date': as_of,
            'company': company.id,
            'results': results,
            'total_unrealized': total_unrealized,
        }

    def action_print_report(self):
        self.ensure_one()
        data = self._compute_unrealized_data()
        return self.env.ref(
            'hudson_accounting_enhancements.action_report_unrealized_currency'
        ).report_action(self, data={'form': data})
