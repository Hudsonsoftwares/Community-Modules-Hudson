from odoo import api, fields, models

class KnowledgeTemplate(models.Model):
    _name = 'knowledge.management.template'
    _description = 'Knowledge Template'
    
    name = fields.Char(string='Name', required=True)
    description = fields.Text(string='Description')
    content = fields.Html(string='Template Content')
    category_id = fields.Many2one('knowledge.management.category', string='Category')
