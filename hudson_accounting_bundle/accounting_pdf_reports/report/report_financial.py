import time
from odoo import api, models, _
from odoo.exceptions import UserError


class ReportFinancial(models.AbstractModel):
    _name = 'report.accounting_pdf_reports.report_financial'
    _description = 'Financial Reports'

    def _compute_account_balance(self, accounts):
        """ compute the balance, debit and credit for the provided accounts
        """
        mapping = {
            'balance': "COALESCE(SUM(debit),0) - COALESCE(SUM(credit), 0) as balance",
            'debit': "COALESCE(SUM(debit), 0) as debit",
            'credit': "COALESCE(SUM(credit), 0) as credit",
        }

        res = {}
        for account in accounts:
            res[account.id] = dict.fromkeys(mapping, 0.0)
        if accounts:
            tables, where_clause, where_params = self.env['account.move.line']._query_get()
            tables = tables.replace('"', '') if tables else "account_move_line"
            wheres = [""]
            if where_clause.strip():
                wheres.append(where_clause.strip())
            filters = " AND ".join(wheres)
            request = "SELECT account_id as id, " + ', '.join(mapping.values()) + \
                       " FROM " + tables + \
                       " WHERE account_id IN %s " \
                            + filters + \
                       " GROUP BY account_id"
            params = (tuple(accounts._ids),) + tuple(where_params)
            self.env.cr.execute(request, params)
            for row in self.env.cr.dictfetchall():
                res[row['id']] = row
        return res

    def _compute_report_balance(self, reports):
        '''returns a dictionary with key=the ID of a record and value=the credit, debit and balance amount
           computed for this record. If the record is of type :
               'accounts' : it's the sum of the linked accounts
               'account_type' : it's the sum of leaf accoutns with such an account_type
               'account_report' : it's the amount of the related report
               'sum' : it's the sum of the children of this record (aka a 'view' record)'''
        res = {}
        fields = ['credit', 'debit', 'balance']
        for report in reports:
            if report.id in res:
                continue
            res[report.id] = dict((fn, 0.0) for fn in fields)
            if report.type == 'accounts':
                # it's the sum of the linked accounts
                res[report.id]['account'] = self._compute_account_balance(report.account_ids)
                for value in res[report.id]['account'].values():
                    for field in fields:
                        res[report.id][field] += value.get(field)
            elif report.type == 'account_type':
                # it's the sum the leaf accounts with such an account type
                accounts = self.env['account.account'].search(
                    [('account_type', 'in', report.account_type_ids.mapped('type'))])

                res[report.id]['account'] = self._compute_account_balance(accounts)
                for value in res[report.id]['account'].values():
                    for field in fields:
                        res[report.id][field] += value.get(field)
            elif report.type == 'account_report' and report.account_report_id:
                # it's the amount of the linked report
                res2 = self._compute_report_balance(report.account_report_id)
                for key, value in res2.items():
                    for field in fields:
                        res[report.id][field] += value[field]
            elif report.type == 'sum':
                # it's the sum of the children of this account.report
                res2 = self._compute_report_balance(report.children_ids)
                for key, value in res2.items():
                    for field in fields:
                        res[report.id][field] += value[field]
        return res

    def get_account_lines(self, data):
        lines = []
        account_report = self.env['account.financial.report'].search(
            [('id', '=', data['account_report_id'][0])])
        child_reports = account_report._get_children_by_order()
        res = self.with_context(data.get('used_context'))._compute_report_balance(child_reports)
        if data['enable_filter']:
            comparison_res = self.with_context(
                data.get('comparison_context'))._compute_report_balance(
                child_reports)
            for report_id, value in comparison_res.items():
                res[report_id]['comp_bal'] = value['balance']
                report_acc = res[report_id].get('account')
                if report_acc:
                    for account_id, val in comparison_res[report_id].get('account').items():
                        report_acc[account_id]['comp_bal'] = val['balance']

        is_pl = account_report and ('profit' in account_report.name.lower() or 'loss' in account_report.name.lower())
        section_balances = {}
        added_summaries = set()

        def get_sec(keywords):
            for k, v in section_balances.items():
                if any(kw in k for kw in keywords):
                    return v
            return {'balance': 0.0, 'balance_cmp': 0.0, 'debit': 0.0, 'credit': 0.0}

        def make_summary_row(name, bal, bal_cmp, deb, cred):
            s_vals = {
                'name': name,
                'balance': bal,
                'type': 'report',
                'level': 1,
                'account_type': False,
                'is_summary_total': True,
            }
            if data['debit_credit']:
                s_vals['debit'] = deb
                s_vals['credit'] = cred
            if data['enable_filter']:
                s_vals['balance_cmp'] = bal_cmp
            return s_vals

        for report in child_reports:
            rep_name = (report.name or '').strip().lower()
            rep_bal = res[report.id]['balance'] * float(report.sign)
            rep_cmp = res[report.id].get('comp_bal', 0.0) * float(report.sign) if data['enable_filter'] else 0.0
            rep_debit = res[report.id].get('debit', 0.0) if data['debit_credit'] else 0.0
            rep_credit = res[report.id].get('credit', 0.0) if data['debit_credit'] else 0.0

            section_balances[rep_name] = {
                'balance': rep_bal,
                'balance_cmp': rep_cmp,
                'debit': rep_debit,
                'credit': rep_credit,
            }

            vals = {
                'name': report.name,
                'balance': rep_bal,
                'type': 'report',
                'level': bool(report.style_overwrite) and report.style_overwrite or report.level,
                'account_type': report.type or False, #used to underline the financial report balances
            }
            if data['debit_credit']:
                vals['debit'] = rep_debit
                vals['credit'] = rep_credit

            if data['enable_filter']:
                vals['balance_cmp'] = rep_cmp

            lines.append(vals)
            if report.display_detail != 'no_detail' and res[report.id].get('account'):
                sub_lines = []
                for account_id, value in res[report.id]['account'].items():
                    flag = False
                    account = self.env['account.account'].browse(account_id)
                    vals = {
                        'name': (account.code + ' ' if account.code else '') + (account.name or ''),
                        'balance': value['balance'] * float(report.sign) or 0.0,
                        'type': 'account',
                        'level': 4 if report.display_detail == 'detail_with_hierarchy' else 2,
                        'account_type': account.account_type,
                    }
                    if data['debit_credit']:
                        vals['debit'] = value['debit']
                        vals['credit'] = value['credit']
                        if not self.env.company.currency_id.is_zero(vals['debit']) or not self.env.company.currency_id.is_zero(vals['credit']):
                            flag = True
                    if not self.env.company.currency_id.is_zero(vals['balance']):
                        flag = True
                    if data['enable_filter']:
                        vals['balance_cmp'] = value['comp_bal'] * float(report.sign)
                        if not self.env.company.currency_id.is_zero(vals['balance_cmp']):
                            flag = True
                    if flag:
                        sub_lines.append(vals)
                lines += sorted(sub_lines, key=lambda sub_line: sub_line['name'])

            if is_pl:
                # 1. Gross Profit: Inserted immediately after Costs of Revenue
                if 'cost' in rep_name and 'gross_profit' not in added_summaries:
                    rev = get_sec(['revenue', 'income'])
                    cor = get_sec(['cost'])
                    gp_bal = rev['balance'] - cor['balance']
                    gp_cmp = rev['balance_cmp'] - cor['balance_cmp']
                    gp_deb = rev['debit'] + cor['debit']
                    gp_crd = rev['credit'] + cor['credit']
                    lines.append(make_summary_row(_('Gross Profit'), gp_bal, gp_cmp, gp_deb, gp_crd))
                    added_summaries.add('gross_profit')

                # 2. Operating Income (or Loss): Inserted immediately after Operating Expenses
                elif ('operating expense' in rep_name or ('expense' in rep_name and 'cost' not in rep_name and 'other' not in rep_name)) and 'operating_income' not in added_summaries:
                    rev = get_sec(['revenue', 'income'])
                    cor = get_sec(['cost'])
                    opex = get_sec(['operating expense', 'expense'])
                    gp_bal = rev['balance'] - cor['balance']
                    gp_cmp = rev['balance_cmp'] - cor['balance_cmp']
                    op_inc_bal = gp_bal - opex['balance']
                    op_inc_cmp = gp_cmp - opex['balance_cmp']
                    op_inc_deb = rev['debit'] + cor['debit'] + opex['debit']
                    op_inc_crd = rev['credit'] + cor['credit'] + opex['credit']
                    lines.append(make_summary_row(_('Operating Income (or Loss)'), op_inc_bal, op_inc_cmp, op_inc_deb, op_inc_crd))
                    added_summaries.add('operating_income')

                # 3. Net Profit: Inserted immediately after Other Expenses
                elif 'other expense' in rep_name and 'net_profit' not in added_summaries:
                    rev = get_sec(['revenue', 'income'])
                    cor = get_sec(['cost'])
                    opex = get_sec(['operating expense', 'expense'])
                    other_inc = get_sec(['other income'])
                    other_exp = get_sec(['other expense'])
                    gp_bal = rev['balance'] - cor['balance']
                    gp_cmp = rev['balance_cmp'] - cor['balance_cmp']
                    op_inc_bal = gp_bal - opex['balance']
                    op_inc_cmp = gp_cmp - opex['balance_cmp']
                    net_prof_bal = op_inc_bal + other_inc['balance'] - other_exp['balance']
                    net_prof_cmp = op_inc_cmp + other_inc['balance_cmp'] - other_exp['balance_cmp']
                    net_prof_deb = rev['debit'] + cor['debit'] + opex['debit'] + other_inc['debit'] + other_exp['debit']
                    net_prof_crd = rev['credit'] + cor['credit'] + opex['credit'] + other_inc['credit'] + other_exp['credit']
                    lines.append(make_summary_row(_('Net Profit'), net_prof_bal, net_prof_cmp, net_prof_deb, net_prof_crd))
                    added_summaries.add('net_profit')

                # 4. Net Profit Left After Allocations and Withdrawals: Inserted after Allocations and Withdrawals
                elif ('allocation' in rep_name or 'withdrawal' in rep_name) and 'net_profit_left' not in added_summaries:
                    rev = get_sec(['revenue', 'income'])
                    cor = get_sec(['cost'])
                    opex = get_sec(['operating expense', 'expense'])
                    other_inc = get_sec(['other income'])
                    other_exp = get_sec(['other expense'])
                    alloc = get_sec(['allocation', 'withdrawal'])
                    gp_bal = rev['balance'] - cor['balance']
                    gp_cmp = rev['balance_cmp'] - cor['balance_cmp']
                    op_inc_bal = gp_bal - opex['balance']
                    op_inc_cmp = gp_cmp - opex['balance_cmp']
                    net_prof_bal = op_inc_bal + other_inc['balance'] - other_exp['balance']
                    net_prof_cmp = op_inc_cmp + other_inc['balance_cmp'] - other_exp['balance_cmp']
                    net_left_bal = net_prof_bal - alloc['balance']
                    net_left_cmp = net_prof_cmp - alloc['balance_cmp']
                    net_left_deb = rev['debit'] + cor['debit'] + opex['debit'] + other_inc['debit'] + other_exp['debit'] + alloc['debit']
                    net_left_crd = rev['credit'] + cor['credit'] + opex['credit'] + other_inc['credit'] + other_exp['credit'] + alloc['credit']
                    lines.append(make_summary_row(_('Net Profit Left After Allocations and Withdrawals'), net_left_bal, net_left_cmp, net_left_deb, net_left_crd))
                    added_summaries.add('net_profit_left')

        if is_pl:
            # Fallback to ensure all 4 summary rows exist even if certain optional sections were omitted from DB
            rev = get_sec(['revenue', 'income'])
            cor = get_sec(['cost'])
            opex = get_sec(['operating expense', 'expense'])
            other_inc = get_sec(['other income'])
            other_exp = get_sec(['other expense'])
            alloc = get_sec(['allocation', 'withdrawal'])

            gp_bal = rev['balance'] - cor['balance']
            gp_cmp = rev['balance_cmp'] - cor['balance_cmp']
            gp_deb = rev['debit'] + cor['debit']
            gp_crd = rev['credit'] + cor['credit']

            op_inc_bal = gp_bal - opex['balance']
            op_inc_cmp = gp_cmp - opex['balance_cmp']
            op_inc_deb = gp_deb + opex['debit']
            op_inc_crd = gp_crd + opex['credit']

            net_prof_bal = op_inc_bal + other_inc['balance'] - other_exp['balance']
            net_prof_cmp = op_inc_cmp + other_inc['balance_cmp'] - other_exp['balance_cmp']
            net_prof_deb = op_inc_deb + other_inc['debit'] + other_exp['debit']
            net_prof_crd = op_inc_crd + other_inc['credit'] + other_exp['credit']

            net_left_bal = net_prof_bal - alloc['balance']
            net_left_cmp = net_prof_cmp - alloc['balance_cmp']
            net_left_deb = net_prof_deb + alloc['debit']
            net_left_crd = net_prof_crd + alloc['credit']

            if 'gross_profit' not in added_summaries:
                lines.append(make_summary_row(_('Gross Profit'), gp_bal, gp_cmp, gp_deb, gp_crd))
            if 'operating_income' not in added_summaries:
                lines.append(make_summary_row(_('Operating Income (or Loss)'), op_inc_bal, op_inc_cmp, op_inc_deb, op_inc_crd))
            if 'net_profit' not in added_summaries:
                lines.append(make_summary_row(_('Net Profit'), net_prof_bal, net_prof_cmp, net_prof_deb, net_prof_crd))
            if 'net_profit_left' not in added_summaries:
                lines.append(make_summary_row(_('Net Profit Left After Allocations and Withdrawals'), net_left_bal, net_left_cmp, net_left_deb, net_left_crd))

        if account_report and 'balance sheet' in account_report.name.lower():
            liabilities_val = sum(res[r.id]['balance'] * float(r.sign) for r in child_reports if r.name == 'Liabilities' and r.id in res)
            equity_val = sum(res[r.id]['balance'] * float(r.sign) for r in child_reports if r.name == 'Equity' and r.id in res)
            
            summary_vals = {
                'name': _('LIABILITIES + TOTAL EQUITY'),
                'balance': liabilities_val + equity_val,
                'type': 'report',
                'level': 1,
                'account_type': False,
                'is_summary_total': True,
            }
            if data.get('debit_credit'):
                summary_vals['debit'] = sum(res[r.id]['debit'] for r in child_reports if r.name in ('Liabilities', 'Equity') and r.id in res)
                summary_vals['credit'] = sum(res[r.id]['credit'] for r in child_reports if r.name in ('Liabilities', 'Equity') and r.id in res)
            if data.get('enable_filter'):
                comp_liab = sum(res[r.id].get('comp_bal', 0.0) * float(r.sign) for r in child_reports if r.name == 'Liabilities' and r.id in res)
                comp_eq = sum(res[r.id].get('comp_bal', 0.0) * float(r.sign) for r in child_reports if r.name == 'Equity' and r.id in res)
                summary_vals['balance_cmp'] = comp_liab + comp_eq
            lines.append(summary_vals)

        return lines

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data.get('form') or not self.env.context.get('active_model') or not self.env.context.get('active_id'):
            raise UserError(_("Form content is missing, this report cannot be printed."))

        model = self.env.context.get('active_model')
        docs = self.env[model].browse(self.env.context.get('active_id'))
        report_lines = self.get_account_lines(data.get('form'))
        return {
            'doc_ids': self.ids,
            'doc_model': model,
            'data': data['form'],
            'docs': docs,
            'time': time,
            'get_account_lines': report_lines,
        }
