# -*- coding: utf-8 -*-
from odoo import fields, models


class KnowledgeItemStage(models.Model):
    _name = 'knowledge.management.item.stage'
    _description = 'Knowledge Item Stage'
    _order = 'sequence, id'

    name = fields.Char(string='Stage Name', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    article_id = fields.Many2one(
        'knowledge.management.article',
        string='Article',
        ondelete='cascade',
        index=True,
    )
    fold = fields.Boolean(string='Folded in Kanban', default=False)
    color = fields.Integer(string='Color')

    _sql_constraints = [
        ('name_article_uniq', 'UNIQUE(name, article_id)',
         'Stage name must be unique per article.'),
    ]
