"""
Aged Receivable / Aged Payable Report — Community Edition
Replicates Odoo Enterprise's inline aged balance report.
"""
import time
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountAgedReport(models.TransientModel):
    """
    Wizard + result model for the Aged Receivable / Aged Payable report.
    The wizard collects parameters; _compute_aged_lines fills the result lines.
    """
    _name = 'account.aged.report'
    _description = 'Aged Receivable / Payable Report'

    # ── Parameters ──────────────────────────────────────────────────────────
    as_of_date = fields.Date(
        string='As of Date',
        required=True,
        default=lambda *a: fields.Date.today(),
    )
    period_length = fields.Integer(
        string='Period Length (days)',
        required=True,
        default=30,
    )
    account_type = fields.Selection([
        ('receivable', 'Receivable'),
        ('payable', 'Payable'),
    ], string='Account Type', required=True, default='receivable')
    target_move = fields.Selection([
        ('posted', 'Posted Entries'),
        ('all', 'All Entries'),
    ], string='Target Moves', required=True, default='posted')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )
    partner_ids = fields.Many2many(
        'res.partner',
        string='Partners',
        help='Leave empty to include all partners.',
    )

    # ── Computed result lines ────────────────────────────────────────────────
    line_ids = fields.One2many(
        'account.aged.report.line',
        'report_id',
        string='Lines',
    )

    # ── Column headers (computed for display) ───────────────────────────────
    col0_label = fields.Char(compute='_compute_col_labels', string='Period 1')
    col1_label = fields.Char(compute='_compute_col_labels', string='Period 2')
    col2_label = fields.Char(compute='_compute_col_labels', string='Period 3')
    col3_label = fields.Char(compute='_compute_col_labels', string='Period 4')
    col4_label = fields.Char(compute='_compute_col_labels', string='Period 5')

    @api.depends('period_length')
    def _compute_col_labels(self):
        for rec in self:
            p = rec.period_length
            rec.col0_label = f'1 - {p}'
            rec.col1_label = f'{p+1} - {2*p}'
            rec.col2_label = f'{2*p+1} - {3*p}'
            rec.col3_label = f'{3*p+1} - {4*p}'
            rec.col4_label = f'+{4*p}'

    def _get_account_types(self):
        if self.account_type == 'receivable':
            return ['asset_receivable']
        return ['liability_payable']

    def _compute_aged_lines(self):
        """Core computation: generate aged buckets per partner."""
        self.ensure_one()
        cr = self.env.cr
        as_of = self.as_of_date
        p = self.period_length
        company = self.company_id
        state_filter = "AND am.state = 'posted'" if self.target_move == 'posted' else ''
        acc_types = self._get_account_types()

        # Determine cutoff dates for each bucket
        # Buckets are based on DAYS PAST DUE (date_maturity or move date)
        # Bucket 6 = Not yet due (date_maturity >= as_of)
        # Bucket 4 = 1..p days overdue
        # Bucket 3 = p+1..2p days overdue
        # ...
        # Bucket 0 = older than 4*p days overdue

        # Build partner list
        partner_clause = ''
        partner_args = []
        if self.partner_ids:
            partner_clause = 'AND l.partner_id IN %s'
            partner_args = [tuple(self.partner_ids.ids)]

        # Get reconciled after as_of_date (need to re-include those lines)
        cr.execute(
            '''SELECT DISTINCT debit_move_id, credit_move_id
               FROM account_partial_reconcile
               WHERE max_date > %s''',
            (as_of,)
        )
        recon_after = []
        for row in cr.fetchall():
            recon_after += [row[0], row[1]]

        recon_clause = '(l.reconciled IS FALSE)'
        recon_args = []
        if recon_after:
            recon_clause = '(l.reconciled IS FALSE OR l.id IN %s)'
            recon_args = [tuple(recon_after)]

        # Fetch all relevant partners
        query = f'''
            SELECT DISTINCT l.partner_id, rp.name AS partner_name
            FROM account_move_line l
            JOIN account_account aa ON aa.id = l.account_id
            JOIN account_move am ON am.id = l.move_id
            LEFT JOIN res_partner rp ON rp.id = l.partner_id
            WHERE aa.account_type IN %s
              AND l.date <= %s
              AND l.company_id = %s
              {state_filter}
              AND {recon_clause}
              {partner_clause}
            ORDER BY rp.name
        '''
        cr.execute(
            query,
            [tuple(acc_types), as_of, company.id] + recon_args + partner_args
        )
        partners = cr.dictfetchall()
        if not partners:
            return []

        partner_ids = [p_['partner_id'] for p_ in partners if p_['partner_id']]
        partner_id_tuple = tuple(partner_ids) if partner_ids else (0,)

        sign = 1 if self.account_type == 'receivable' else -1

        # Build period date ranges
        periods = {}
        start_date = as_of
        for i in range(4, -1, -1):
            if i == 0:
                # oldest bucket: all before start_date
                periods[i] = {'start': False, 'stop': start_date}
            else:
                stop_date = start_date
                start_date = stop_date - timedelta(days=p)
                periods[i] = {'start': start_date + timedelta(days=1), 'stop': stop_date}
            start_date = start_date - timedelta(days=1)

        def build_date_clause(idx):
            """Build WHERE clause fragment for a bucket."""
            if periods[idx]['start'] and periods[idx]['stop']:
                return "BETWEEN %s AND %s", [periods[idx]['start'].strftime('%Y-%m-%d'),
                                             periods[idx]['stop'].strftime('%Y-%m-%d')]
            elif periods[idx]['stop']:
                return "<= %s", [periods[idx]['stop'].strftime('%Y-%m-%d')]
            else:
                return ">= %s", [periods[idx]['start'].strftime('%Y-%m-%d')]

        # ── Not due (date_maturity >= as_of) ─────────────────────────────
        cr.execute(
            f'''SELECT l.partner_id, COALESCE(SUM(l.balance * {sign}), 0) AS amt
                FROM account_move_line l
                JOIN account_account aa ON aa.id = l.account_id
                JOIN account_move am ON am.id = l.move_id
                WHERE aa.account_type IN %s
                  AND l.date <= %s
                  AND COALESCE(l.date_maturity, l.date) >= %s
                  AND l.company_id = %s
                  {state_filter}
                  AND {recon_clause}
                  AND ((l.partner_id IN %s) OR (l.partner_id IS NULL))
                  AND l.display_type NOT IN ('line_section', 'line_note')
                GROUP BY l.partner_id''',
            [tuple(acc_types), as_of, as_of, company.id] + recon_args + [partner_id_tuple]
        )
        not_due = {row['partner_id']: row['amt'] for row in cr.dictfetchall()}

        # ── Per-period buckets ────────────────────────────────────────────
        bucket_data = {}
        for i in range(5):
            date_op, date_params = build_date_clause(i)
            cr.execute(
                f'''SELECT l.partner_id, COALESCE(SUM(l.balance * {sign}), 0) AS amt
                    FROM account_move_line l
                    JOIN account_account aa ON aa.id = l.account_id
                    JOIN account_move am ON am.id = l.move_id
                    WHERE aa.account_type IN %s
                      AND l.date <= %s
                      AND COALESCE(l.date_maturity, l.date) {date_op}
                      AND l.company_id = %s
                      {state_filter}
                      AND {recon_clause}
                      AND ((l.partner_id IN %s) OR (l.partner_id IS NULL))
                      AND l.display_type NOT IN ('line_section', 'line_note')
                    GROUP BY l.partner_id''',
                [tuple(acc_types), as_of] + date_params + [company.id] + recon_args + [partner_id_tuple]
            )
            bucket_data[i] = {row['partner_id']: row['amt'] for row in cr.dictfetchall()}

        # ── Assemble result rows ──────────────────────────────────────────
        result = []
        totals = {'not_due': 0, 'p0': 0, 'p1': 0, 'p2': 0, 'p3': 0, 'p4': 0, 'total': 0}

        for prow in partners:
            pid = prow['partner_id']
            nd = not_due.get(pid, 0.0)
            p0 = bucket_data[4].get(pid, 0.0)
            p1 = bucket_data[3].get(pid, 0.0)
            p2 = bucket_data[2].get(pid, 0.0)
            p3 = bucket_data[1].get(pid, 0.0)
            p4 = bucket_data[0].get(pid, 0.0)
            total = nd + p0 + p1 + p2 + p3 + p4

            if abs(total) < 0.001:
                continue  # Skip zero-balance partners

            totals['not_due'] += nd
            totals['p0'] += p0
            totals['p1'] += p1
            totals['p2'] += p2
            totals['p3'] += p3
            totals['p4'] += p4
            totals['total'] += total

            result.append({
                'partner_id': pid,
                'partner_name': prow['partner_name'] or _('Unknown'),
                'not_due': nd,
                'p0': p0,
                'p1': p1,
                'p2': p2,
                'p3': p3,
                'p4': p4,
                'total': total,
            })

        return result, totals

    def action_generate(self):
        """Generate / refresh the report lines."""
        self.ensure_one()
        if self.period_length <= 0:
            raise UserError(_('Period length must be greater than 0.'))

        # Clear existing lines
        self.line_ids.unlink()

        try:
            result_and_totals = self._compute_aged_lines()
        except Exception as e:
            raise UserError(str(e))

        if not result_and_totals:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.aged.report',
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }

        rows, totals = result_and_totals

        # Create line records
        Line = self.env['account.aged.report.line']
        for row in rows:
            Line.create({
                'report_id': self.id,
                'partner_id': row['partner_id'],
                'partner_name': row['partner_name'],
                'not_due': row['not_due'],
                'p0': row['p0'],
                'p1': row['p1'],
                'p2': row['p2'],
                'p3': row['p3'],
                'p4': row['p4'],
                'total': row['total'],
            })

        # Create totals row
        Line.create({
            'report_id': self.id,
            'partner_id': False,
            'partner_name': _('TOTAL'),
            'is_total': True,
            'not_due': totals['not_due'],
            'p0': totals['p0'],
            'p1': totals['p1'],
            'p2': totals['p2'],
            'p3': totals['p3'],
            'p4': totals['p4'],
            'total': totals['total'],
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.aged.report',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_print_pdf(self):
        """Print the aged report as PDF."""
        self.ensure_one()
        if not self.line_ids:
            self.action_generate()
        report_action_id = (
            'hudson_accounting_enhancements.action_report_aged_receivable'
            if self.account_type == 'receivable'
            else 'hudson_accounting_enhancements.action_report_aged_payable'
        )
        return self.env.ref(report_action_id).with_context(landscape=True).report_action(self)


class AccountAgedReportLine(models.TransientModel):
    """One partner row in the aged report."""
    _name = 'account.aged.report.line'
    _description = 'Aged Report Line'
    _order = 'is_total asc, partner_name asc'

    report_id = fields.Many2one('account.aged.report', ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string='Partner Link')
    partner_name = fields.Char(string='Partner')
    is_total = fields.Boolean(default=False)

    not_due = fields.Monetary(string='Not Due', currency_field='currency_id')
    p0 = fields.Monetary(string='1-30', currency_field='currency_id')
    p1 = fields.Monetary(string='31-60', currency_field='currency_id')
    p2 = fields.Monetary(string='61-90', currency_field='currency_id')
    p3 = fields.Monetary(string='91-120', currency_field='currency_id')
    p4 = fields.Monetary(string='Older', currency_field='currency_id')
    total = fields.Monetary(string='Total', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency',
    )

    @api.depends('report_id.company_id')
    def _compute_currency(self):
        for rec in self:
            rec.currency_id = rec.report_id.company_id.currency_id
