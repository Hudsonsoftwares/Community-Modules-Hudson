# -*- coding: utf-8 -*-
import json
from odoo import models, fields, api, _

class HudsonReportExportKnowledgeWizard(models.TransientModel):
    _name = 'hudson.report.export.knowledge.wizard'
    _description = 'Insert Report into Knowledge Article'

    article_id = fields.Many2one('knowledge.management.article', string="Article", required=True)
    report_data = fields.Text(string="Report Data JSON")
    name = fields.Char(string="Report Name")

    def action_insert(self):
        self.ensure_one()
        report_data_dict = json.loads(self.report_data or '{}')
        columns = report_data_dict.get('columns', [])
        lines = report_data_dict.get('lines', [])
        date_str = report_data_dict.get('date_str', '')
        
        # Build clean, responsive HTML table snapshot
        html = f"""
        <div class="oe_hudson_report_snapshot" style="margin-top: 20px; margin-bottom: 20px; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
            <div style="background-color: #f8fafc; padding: 14px 20px; border-bottom: 1px solid #e2e8f0;">
                <h3 style="margin: 0; font-size: 18px; font-weight: 700; color: #0f172a;">{self.name}</h3>
                <p style="margin: 4px 0 0 0; font-size: 12px; color: #64748b;">Report Snapshot &bull; {date_str}</p>
            </div>
            <div style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; min-width: 600px; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #f1f5f9; border-bottom: 2px solid #cbd5e1;">
        """
        
        for col in columns:
            align = "right" if col.get('type') == 'monetary' else "left"
            html += f'<th style="padding: 10px 14px; text-align: {align}; font-weight: 600; color: #475569;">{col.get("label", "")}</th>'
            
        html += """
                        </tr>
                    </thead>
                    <tbody>
        """
        
        for line in lines:
            try:
                level = int(line.get('level', 3) or 3)
            except (ValueError, TypeError):
                level = 3
            is_summary_total = bool(line.get('is_summary_total', False))
            bg_color = "#ffffff"
            font_weight = "normal"
            border_bottom = "1px solid #f1f5f9"
            
            if level == 1:
                bg_color = "#f8fafc"
                font_weight = "600"
            if is_summary_total:
                bg_color = "#ffffff"
                font_weight = "bold"
                border_bottom = "2px solid #0f172a"
                
            html += f'<tr style="background-color: {bg_color}; border-bottom: {border_bottom};">'
            
            for i, col in enumerate(columns):
                val = line.get(col.get('field', ''))
                if val is None:
                    val = ''
                align = "right" if col.get('type') == 'monetary' else "left"
                
                if col.get('type') == 'monetary' and isinstance(val, (int, float)):
                    val = f"{val:,.2f}"
                
                padding_left = "14px"
                if i == 0 and level > 1 and not is_summary_total:
                    padding_left = f"{14 + (level-1)*15}px"
                    
                html += f'<td style="padding: 8px 14px; padding-left: {padding_left}; text-align: {align}; color: #1e293b; font-weight: {font_weight};">{val}</td>'
                
            html += "</tr>"
            
        html += """
                    </tbody>
                </table>
            </div>
        </div>
        """
        
        # Append snapshot to the article content
        current_content = self.article_id.content or ""
        self.article_id.write({'content': current_content + html})
            
        return {
            'type': 'ir.actions.act_window',
            'name': _('Article'),
            'res_model': 'knowledge.management.article',
            'res_id': self.article_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
