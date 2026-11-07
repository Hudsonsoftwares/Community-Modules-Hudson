# -*- coding: utf-8 -*-
import json

from markupsafe import Markup

from odoo import models, fields, _
from odoo.exceptions import UserError


class HudsonReportExportKnowledgeWizard(models.TransientModel):
    _name = 'hudson.report.export.knowledge.wizard'
    _description = 'Insert Report into Knowledge Article'

    article_id = fields.Many2one(
        'knowledge.management.article', string="Article", required=True,
        domain="[('is_locked', '=', False)]",
        help="The report is added at the end of this article.")
    # The report as displayed, sent by the report screen (see _getExportPayload in dynamic_report.js)
    report_data = fields.Text(string="Report Data JSON")
    name = fields.Char(string="Report Name")

    def action_insert(self):
        self.ensure_one()
        try:
            payload = json.loads(self.report_data or '{}')
        except ValueError:
            payload = {}
        if not isinstance(payload, dict) or not payload.get('columns'):
            raise UserError(_("There is no report data to insert. Reopen the report and try again."))

        article = self.article_id
        if article.is_locked:
            raise UserError(_("The article %s is locked. Unlock it before inserting a report.", article.name))
        article.check_access('write')

        # The article body is stored unsanitized: the snapshot escapes every value
        snapshot = self.env['hudson.report.snapshot'].render_html(payload, name=self.name or payload.get('title'))
        article.write({'body_html': Markup(article.body_html or '') + snapshot})

        return {
            'type': 'ir.actions.client',
            'tag': 'hudson_knowledge.action_knowledge',
            'params': {'res_id': article.id},
        }
