from odoo import api, fields, models

class KnowledgeTag(models.Model):
    _name = 'knowledge.management.tag'
    _description = 'Knowledge Tag'
    
    name = fields.Char(string='Name', required=True)
    color = fields.Integer(string='Color Index')
