# -*- coding: utf-8 -*-
from odoo import fields, models


class KnowledgeArticleMember(models.Model):
    _name = 'knowledge.management.article.member'
    _description = 'Knowledge Article Member'
    _rec_name = 'partner_id'

    article_id = fields.Many2one(
        'knowledge.management.article',
        string='Article',
        required=True,
        ondelete='cascade',
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Contact',
        required=True,
        ondelete='cascade',
    )
    permission = fields.Selection([
        ('read', 'Can Read'),
        ('write', 'Can Write'),
    ], string='Permission', default='read', required=True)
