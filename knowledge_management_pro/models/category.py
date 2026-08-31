from odoo import api, fields, models

class KnowledgeCategory(models.Model):
    _name = 'knowledge.management.category'
    _description = 'Knowledge Category'
    
    name = fields.Char(string='Name', required=True)
    parent_id = fields.Many2one('knowledge.management.category', string='Parent Category', index=True, ondelete='cascade')
    child_ids = fields.One2many('knowledge.management.category', 'parent_id', string='Child Categories')
