# -*- coding: utf-8 -*-
from odoo import fields, models


class KnowledgeArticleTemplate(models.Model):
    _name = 'knowledge.management.article.template'
    _description = 'Knowledge Article Template'
    _order = 'sequence, id'

    name = fields.Char(string='Template Name', required=True)
    description = fields.Char(string='Description')
    icon = fields.Char(string='Icon', default='📋')
    body_html = fields.Html(
        string='Template Body',
        sanitize=False,
        strip_style=False,
    )
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)

    def action_use_template(self):
        """Create a new article from this template."""
        self.ensure_one()
        article = self.env['knowledge.management.article'].create({
            'name': self.name,
            'icon': self.icon,
            'body_html': self.body_html,
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'hudson_knowledge.action_knowledge',
            'params': {'res_id': article.id},
        }
