from odoo import api, fields, models

class KnowledgeArticle(models.Model):
    _name = 'knowledge.management.article'
    _description = 'Knowledge Article'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'website.published.mixin']

    name = fields.Char(string='Title', required=True, tracking=True)
    icon = fields.Char(string='Icon', size=20)
    cover_image = fields.Binary(string='Cover Image', attachment=True)
    cover_position = fields.Float(string='Cover Position Y', default=50.0)
    content = fields.Html(string='Content', sanitize=False)
    is_locked = fields.Boolean(string='Locked', default=False, tracking=True)
    
    workspace_id = fields.Many2one('knowledge.management.workspace', string='Workspace', tracking=True)
    category_id = fields.Many2one('knowledge.management.category', string='Category', tracking=True)
    tag_ids = fields.Many2many('knowledge.management.tag', string='Tags')
    
    parent_id = fields.Many2one('knowledge.management.article', string='Parent Article', index=True, ondelete='cascade')
    child_ids = fields.One2many('knowledge.management.article', 'parent_id', string='Child Articles')
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('review', 'In Review'),
        ('published', 'Published'),
        ('archived', 'Archived')
    ], string='Status', default='draft', tracking=True)
    
    is_private = fields.Boolean(string='Private', default=False, tracking=True)
    author_id = fields.Many2one('res.users', string='Author', default=lambda self: self.env.user, tracking=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    
    favorite_user_ids = fields.Many2many('res.users', 'km_article_favorite_rel', 'article_id', 'user_id', string='Favorited By')
    bookmark_user_ids = fields.Many2many('res.users', 'km_article_bookmark_rel', 'article_id', 'user_id', string='Bookmarked By')
    
    version_ids = fields.One2many('knowledge.management.version', 'article_id', string='Versions')
    comment_ids = fields.One2many('knowledge.management.comment', 'article_id', string='Comments')
    share_ids = fields.One2many('knowledge.management.share', 'article_id', string='Shares')
    shared_partner_ids = fields.Many2many('res.partner', compute='_compute_shared_partner_ids', string='Shared Contacts')
    
    @api.depends('share_ids.partner_ids')
    def _compute_shared_partner_ids(self):
        for rec in self:
            rec.shared_partner_ids = rec.share_ids.mapped('partner_ids')
            
    template_id = fields.Many2one('knowledge.management.template', string='Template')

    @api.onchange('template_id')
    def _onchange_template_id(self):
        if self.template_id:
            if not self.name and self.template_id.name:
                self.name = self.template_id.name
            if not self.content and self.template_id.content:
                self.content = self.template_id.content
            if not self.category_id and self.template_id.category_id:
                self.category_id = self.template_id.category_id

    
    expiration_date = fields.Date(string='Expiration Date', tracking=True)
    needs_review = fields.Boolean(string='Needs Review', default=False, tracking=True)
    reviewer_id = fields.Many2one('res.users', string='Reviewer', tracking=True)

    def _compute_website_url(self):
        super(KnowledgeArticle, self)._compute_website_url()
        for article in self:
            article.website_url = '/knowledge/article/%s' % article.id

    def action_submit_review(self):
        for rec in self:
            rec.state = 'review'

    def action_publish(self):
        for rec in self:
            rec.state = 'published'

    def action_archive(self):
        for rec in self:
            rec.state = 'archived'
            
    def write(self, vals):
        res = super(KnowledgeArticle, self).write(vals)
        if 'content' in vals or 'name' in vals:
            now = fields.Datetime.now()
            for article in self:
                # Find the latest version
                last_version = self.env['knowledge.management.version'].search([
                    ('article_id', '=', article.id)
                ], order='date desc', limit=1)
                
                create_snapshot = False
                
                if not last_version:
                    create_snapshot = True
                else:
                    # Create if last version is older than 10 minutes OR different user
                    time_diff = now - last_version.date
                    if time_diff.total_seconds() > 600 or last_version.user_id.id != self.env.user.id:
                        create_snapshot = True
                        
                if create_snapshot:
                    version_num = (last_version.version_number + 1) if last_version else 1
                    self.env['knowledge.management.version'].create({
                        'article_id': article.id,
                        'version_number': version_num,
                        'user_id': self.env.user.id,
                        'date': now,
                        'content_snapshot': article.content,
                        'change_summary': f"Auto-saved version {version_num}"
                    })
        return res
