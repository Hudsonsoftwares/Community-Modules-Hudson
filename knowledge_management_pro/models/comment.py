from odoo import api, fields, models

class KnowledgeComment(models.Model):
    _name = 'knowledge.management.comment'
    _description = 'Knowledge Comment'
    
    article_id = fields.Many2one('knowledge.management.article', string='Article', required=True, ondelete='cascade')
    content = fields.Html(string='Comment', required=True)
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    date = fields.Datetime(string='Date', default=fields.Datetime.now)
    parent_id = fields.Many2one('knowledge.management.comment', string='Parent Comment', index=True, ondelete='cascade')
    is_resolved = fields.Boolean(string='Resolved', default=False)
    anchor_id = fields.Char(string='Anchor ID', help="ID of the HTML element this comment is anchored to")
