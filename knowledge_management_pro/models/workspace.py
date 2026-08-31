from odoo import api, fields, models

class KnowledgeWorkspace(models.Model):
    _name = 'knowledge.management.workspace'
    _description = 'Knowledge Workspace'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Name', required=True, tracking=True)
    description = fields.Text(string='Description')
    color = fields.Integer(string='Color Index')
    
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    
    article_ids = fields.One2many('knowledge.management.article', 'workspace_id', string='Articles')
    
    manager_ids = fields.Many2many('res.users', string='Managers', tracking=True)
    is_private = fields.Boolean(string='Private Workspace', default=False, tracking=True)
