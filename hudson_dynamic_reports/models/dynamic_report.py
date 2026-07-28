from odoo import api, models, _
from odoo.exceptions import UserError

class HudsonDynamicReport(models.AbstractModel):
    _name = "hudson.dynamic.report"
    _description = "Dynamic Report Endpoint"

    @api.model
    def get_report_data(self, model_name, wizard_id, data):
        error_result = {
            'title': _('Session Expired'),
            'columns': [{'label': 'Message', 'field': 'message'}],
            'lines': [{'id': 'error', 'message': _('Report session expired or parameters missing. Please generate the report again from the menu.')}],
            'currency_id': self.env.company.currency_id.id,
            'company_id': self.env.company.id,
        }
        
        if not model_name or not wizard_id:
            return error_result

        wizard = self.env[model_name].browse(wizard_id)
        if not wizard.exists():
            return error_result

        form_data = data.get('form', data)
        result = {
            'title': 'Report',
            'columns': [],
            'lines': [],
            'currency_id': self.env.company.currency_id.id,
            'company_id': self.env.company.id,
        }

        if model_name == 'accounting.report':
            # Profit and Loss / Balance Sheet
            report_name = form_data.get('account_report_id')
            if isinstance(report_name, list) and len(report_name) > 1:
                result['title'] = report_name[1]
            elif isinstance(report_name, tuple) and len(report_name) > 1:
                result['title'] = report_name[1]
            else:
                result['title'] = _("Financial Report")
                
            debit_credit = form_data.get('debit_credit')
            enable_filter = form_data.get('enable_filter')
            
            result['columns'] = [{'label': 'Name', 'field': 'name'}]
            if debit_credit:
                result['columns'].append({'label': 'Debit', 'field': 'debit', 'type': 'monetary'})
                result['columns'].append({'label': 'Credit', 'field': 'credit', 'type': 'monetary'})
            result['columns'].append({'label': 'Balance', 'field': 'balance', 'type': 'monetary'})
            if enable_filter:
                result['columns'].append({'label': form_data.get('label_filter') or 'Comparison', 'field': 'balance_cmp', 'type': 'monetary'})
            
            report_model = self.env['report.accounting_pdf_reports.report_financial']
            lines = report_model.with_context(active_model=model_name).get_account_lines(form_data)
            
            formatted_lines = []
            for line in lines:
                formatted_lines.append({
                    'id': str(line.get('type')) + '_' + str(line.get('name')),
                    'name': line.get('name', ''),
                    'debit': line.get('debit', 0.0),
                    'credit': line.get('credit', 0.0),
                    'balance': line.get('balance', 0.0),
                    'balance_cmp': line.get('balance_cmp', 0.0),
                    'level': line.get('level', 1),
                    'type': line.get('type', 'report'),
                })
            result['lines'] = formatted_lines

        elif model_name == 'account.tax.report.wizard':
            result['title'] = _("Tax Report")
            result['columns'] = [
                {'label': 'Name', 'field': 'name'},
                {'label': 'Net', 'field': 'net', 'type': 'monetary'},
                {'label': 'Tax', 'field': 'tax', 'type': 'monetary'},
            ]
            report_model = self.env['report.accounting_pdf_reports.report_tax']
            groups = report_model.with_context(active_model=model_name).get_lines(form_data)
            
            formatted_lines = []
            for group_name, group_lines in groups.items():
                if group_lines:
                    formatted_lines.append({
                        'id': f'group_{group_name}',
                        'name': group_name.capitalize(),
                        'level': 1,
                        'type': 'group',
                    })
                    for idx, line in enumerate(group_lines):
                        formatted_lines.append({
                            'id': f'tax_{group_name}_{idx}',
                            'name': line.get('name', ''),
                            'net': line.get('net', 0.0),
                            'tax': line.get('tax', 0.0),
                            'level': 2,
                            'type': 'tax',
                        })
            result['lines'] = formatted_lines
        else:
            result['title'] = _("Report")
            result['columns'] = [{'label': 'Name', 'field': 'name'}]
            
        return result
