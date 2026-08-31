from odoo import api, fields, models

class KnowledgeHistory(models.Model):
    _name = 'knowledge.management.history'
    _description = 'Knowledge Access History'
    
    article_id = fields.Many2one('knowledge.management.article', string='Article', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    date = fields.Datetime(string='Date', default=fields.Datetime.now)
    action = fields.Selection([
        ('view', 'Viewed'),
        ('edit', 'Edited'),
        ('share', 'Shared')
    ], string='Action', default='view')
