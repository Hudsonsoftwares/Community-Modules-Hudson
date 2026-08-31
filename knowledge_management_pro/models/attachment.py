from odoo import api, fields, models

class KnowledgeAttachment(models.Model):
    _name = 'knowledge.management.attachment'
    _description = 'Knowledge Attachment'
    
    name = fields.Char(string='Name', required=True)
    article_id = fields.Many2one('knowledge.management.article', string='Article', required=True, ondelete='cascade')
    file = fields.Binary(string='File', required=True)
    mimetype = fields.Char(string='Mime Type')
