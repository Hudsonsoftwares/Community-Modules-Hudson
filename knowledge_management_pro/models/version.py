from odoo import api, fields, models

class KnowledgeVersion(models.Model):
    _name = 'knowledge.management.version'
    _description = 'Knowledge Version History'
    
    article_id = fields.Many2one('knowledge.management.article', string='Article', required=True, ondelete='cascade')
    version_number = fields.Integer(string='Version', default=1)
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    date = fields.Datetime(string='Date', default=fields.Datetime.now)
    title_snapshot = fields.Char(string='Title Snapshot')
    content_snapshot = fields.Html(string='Content Snapshot', sanitize=True)
    change_summary = fields.Char(string='Change Summary')
    change_type = fields.Selection([
        ('create', 'Created'),
        ('update', 'Updated'),
        ('restore', 'Restored')
    ], string='Change Type', default='update')

    _sql_constraints = [
        ('article_version_unique', 'unique(article_id, version_number)', 'Version numbers must be unique per article.')
    ]
