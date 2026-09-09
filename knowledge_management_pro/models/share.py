from odoo import api, fields, models

class KnowledgeShare(models.Model):
    _name = 'knowledge.management.share'
    _description = 'Knowledge Share configuration'
    
    article_id = fields.Many2one('knowledge.management.article', string='Article', required=True, ondelete='cascade')
    user_ids = fields.Many2many('res.users', string='Shared With Users')
    partner_ids = fields.Many2many('res.partner', string='Shared With Partners')
    access_level = fields.Selection([
        ('none', 'No access'),
        ('read', 'Read'),
        ('write', 'Write')
    ], string='Access Level', default='read')
