# -*- coding: utf-8 -*-
import json
import io
import base64
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class HudsonReportExportDMSWizard(models.TransientModel):
    _name = 'hudson.report.export.dms.wizard'
    _description = 'Export Report to Documents'

    name = fields.Char(string="Document Name", required=True)
    directory_id = fields.Many2one('dms.directory', string="Folder", required=True)
    tag_ids = fields.Many2many('dms.tag', string="Tags")
    export_format = fields.Selection([
        ('pdf', 'PDF'),
        ('xlsx', 'XLSX')
    ], string="Export Format", default='pdf', required=True)

    report_data = fields.Text(string="Report Data JSON")
    model_name = fields.Char(string="Model Name")
    wizard_id = fields.Integer(string="Wizard ID")

    def _build_html_snapshot(self):
        report_data_dict = json.loads(self.report_data or '{}')
        columns = report_data_dict.get('columns', [])
        lines = report_data_dict.get('lines', [])
        date_str = report_data_dict.get('date_str', '')
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8"/>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 25px; color: #1e293b; font-size: 12px; }}
                h2 {{ color: #0f172a; margin-bottom: 4px; font-size: 20px; }}
                p.date {{ color: #64748b; font-size: 13px; margin-top: 0; margin-bottom: 20px; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th {{ background-color: #f1f5f9; padding: 10px 8px; border-bottom: 2px solid #cbd5e1; font-weight: bold; }}
                td {{ padding: 6px 8px; border-bottom: 1px solid #f1f5f9; }}
                .bold {{ font-weight: bold; background-color: #f8fafc; }}
                .total {{ font-weight: bold; border-bottom: 2px solid #0f172a; border-top: 1px solid #0f172a; }}
                .text-right {{ text-align: right; }}
                .text-left {{ text-align: left; }}
            </style>
        </head>
        <body>
            <h2>{self.name}</h2>
            <p class="date">{date_str}</p>
            <table>
                <thead>
                    <tr>
        """
        for col in columns:
            align = "text-right" if col.get('type') == 'monetary' else "text-left"
            html_content += f'<th class="{align}">{col.get("label", "")}</th>'
        html_content += "</tr></thead><tbody>"
        
        for line in lines:
            try:
                level = int(line.get('level', 3) or 3)
            except (ValueError, TypeError):
                level = 3
            is_summary = bool(line.get('is_summary_total', False))
            row_cls = "total" if is_summary else ("bold" if level == 1 else "")
            html_content += f'<tr class="{row_cls}">'
            for i, col in enumerate(columns):
                val = line.get(col.get('field', ''))
                if val is None:
                    val = ''
                align = "text-right" if col.get('type') == 'monetary' else "text-left"
                if col.get('type') == 'monetary' and isinstance(val, (int, float)):
                    val = f"{val:,.2f}"
                pad = f"padding-left: {8 + (level-1)*14}px;" if i == 0 and level > 1 and not is_summary else ""
                html_content += f'<td class="{align}" style="{pad}">{val}</td>'
            html_content += "</tr>"
        html_content += "</tbody></table></body></html>"
        return html_content

    def action_export(self):
        self.ensure_one()
        file_content = b''
        extension = ''
        mimetype = ''

        if self.export_format == 'xlsx':
            extension = '.xlsx'
            mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            try:
                import xlsxwriter
                report_data_dict = json.loads(self.report_data or '{}')
                output = io.BytesIO()
                workbook = xlsxwriter.Workbook(output, {'in_memory': True})
                worksheet = workbook.add_worksheet(self.name[:31])
                
                format_title = workbook.add_format({'font_size': 14, 'bold': True})
                format_header = workbook.add_format({'bold': True, 'bottom': 2, 'align': 'right'})
                format_header_left = workbook.add_format({'bold': True, 'bottom': 2, 'align': 'left'})
                
                columns = report_data_dict.get('columns', [])
                lines = report_data_dict.get('lines', [])
                
                worksheet.write(0, 0, self.name, format_title)
                row = 2
                for i, col in enumerate(columns):
                    fmt = format_header_left if col.get('field') == 'name' else format_header
                    worksheet.write(row, i, col.get('label', ''), fmt)
                
                row += 1
                for line in lines:
                    for i, col in enumerate(columns):
                        val = line.get(col.get('field', ''))
                        worksheet.write(row, i, val if val is not None else '')
                    row += 1
                
                workbook.close()
                file_content = output.getvalue()
            except Exception as e:
                raise UserError(_("Could not generate XLSX: %s") % str(e))
                
        elif self.export_format == 'pdf':
            extension = '.pdf'
            mimetype = 'application/pdf'
            
            # 1. Try backend QWeb report with proper active context
            if self.model_name and self.wizard_id:
                try:
                    context = {
                        'active_model': self.model_name,
                        'active_id': self.wizard_id,
                        'active_ids': [self.wizard_id],
                    }
                    wiz = self.env[self.model_name].with_context(**context).browse(self.wizard_id)
                    if wiz.exists() and hasattr(wiz, 'check_report'):
                        action = wiz.with_context(**context).check_report()
                        if action and action.get('type') == 'ir.actions.report':
                            report_ref = action.get('report_name')
                            report_data = action.get('data') or {}
                            pdf_res, ext_type = self.env['ir.actions.report'].with_context(**context)._render_qweb_pdf(report_ref, [self.wizard_id], data=report_data)
                            if pdf_res:
                                file_content = pdf_res
                except Exception as e:
                    _logger.warning("Direct QWeb PDF render failed: %s", e)

            # 2. If wizard was transiently cleared or dynamic, instantiate standard financial report
            if not file_content and (self.model_name == 'accounting.report' or 'balance' in (self.name or '').lower() or 'profit' in (self.name or '').lower()):
                try:
                    report_title = (self.name or '').lower()
                    if 'profit' in report_title or 'loss' in report_title:
                        rep = self.env.ref('accounting_pdf_reports.account_financial_report_profitandloss0', raise_if_not_found=False)
                    else:
                        rep = self.env.ref('accounting_pdf_reports.account_financial_report_balancesheet0', raise_if_not_found=False)
                    if rep:
                        temp_wiz = self.env['accounting.report'].create({'account_report_id': rep.id})
                        ctx = {'active_model': 'accounting.report', 'active_id': temp_wiz.id, 'active_ids': [temp_wiz.id]}
                        action = temp_wiz.with_context(**ctx).check_report()
                        if action and action.get('type') == 'ir.actions.report':
                            report_ref = action.get('report_name')
                            report_data = action.get('data') or {}
                            pdf_res, ext_type = self.env['ir.actions.report'].with_context(**ctx)._render_qweb_pdf(report_ref, [temp_wiz.id], data=report_data)
                            if pdf_res:
                                file_content = pdf_res
                except Exception as e:
                    _logger.warning("Recreated financial report PDF render failed: %s", e)
            
            # 3. Fallback: Convert HTML snapshot directly to PDF using wkhtmltopdf
            if not file_content:
                try:
                    html_content = self._build_html_snapshot()
                    pdf_res = self.env['ir.actions.report']._run_wkhtmltopdf([html_content])
                    if pdf_res:
                        file_content = pdf_res
                except Exception as e:
                    _logger.warning("wkhtmltopdf HTML snapshot conversion failed: %s", e)

            if not file_content:
                raise UserError(_("Could not generate PDF for this report. Please select XLSX format to export to Documents."))

        if file_content:
            filename = f"{self.name}{extension}"
            dms_file = self.env['dms.file'].create({
                'name': filename,
                'directory_id': self.directory_id.id,
                'tag_ids': [(6, 0, self.tag_ids.ids)],
                'content': base64.b64encode(file_content),
            })
            return {
                'type': 'ir.actions.act_window',
                'name': _('Document Created'),
                'res_model': 'dms.file',
                'res_id': dms_file.id,
                'view_mode': 'form',
                'target': 'current',
            }
