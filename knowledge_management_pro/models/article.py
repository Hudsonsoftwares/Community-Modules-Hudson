import logging
import requests
import base64

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class KnowledgeArticle(models.Model):
    _name = 'knowledge.management.article'
    _description = 'Knowledge Article'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'website.published.mixin']
    _parent_store = True
    _parent_name = 'parent_id'
    _order = 'sequence asc, name asc, write_date desc'

    _sql_constraints = [
        ('name_unique', 'unique(name)', 'The name of the article must be unique!')
    ]

    REQUEST_TIMEOUT = 3
    DEFAULT_RESTORE_SEQUENCE = 10

    name = fields.Char(string='Title', required=True, tracking=True)
    sequence = fields.Integer('Sequence')
    icon = fields.Char(string='Icon', size=20)
    cover_image = fields.Binary(string='Cover Image', attachment=True)
    cover_position = fields.Float(string='Cover Position Y', default=50.0)
    content = fields.Html(string='Content', sanitize=True)
    is_locked = fields.Boolean(string='Locked', default=False, tracking=True)
    is_full_width = fields.Boolean(string="Full Width Canvas", default=False)
    active = fields.Boolean(default=True)
    in_trash = fields.Boolean(string="In Trash", default=False, index=True)
    previous_parent_id = fields.Many2one('knowledge.management.article', string="Previous Parent")
    previous_sequence = fields.Integer(string="Previous Sequence")
    
    workspace_id = fields.Many2one('knowledge.management.workspace', string='Workspace', tracking=True, index=True)
    category_id = fields.Many2one('knowledge.management.category', string='Category', tracking=True, index=True)
    tag_ids = fields.Many2many('knowledge.management.tag', string='Tags')
    
    parent_id = fields.Many2one('knowledge.management.article', string='Parent Article', index=True, ondelete='restrict')
    child_ids = fields.One2many('knowledge.management.article', 'parent_id', string='Child Articles')
    parent_path = fields.Char(index=True)
    
    @api.constrains('parent_id')
    def _check_hierarchy(self):
        """Check that the article hierarchy is not recursive."""
        if not self._check_recursion():
            _logger.warning("Attempted to create a recursive article structure for article ID %s", self.id)
            raise ValidationError(_('Error! You cannot create recursive articles.'))
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('review', 'In Review'),
        ('published', 'Published'),
        ('archived', 'Archived')
    ], string='Status', default='draft', tracking=True)
    
    is_private = fields.Boolean(string='Private', default=False, tracking=True)
    author_id = fields.Many2one('res.users', string='Author', default=lambda self: self.env.user, tracking=True, index=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    
    favorite_user_ids = fields.Many2many('res.users', 'km_article_favorite_rel', 'article_id', 'user_id', string='Favorited By')
    is_favorite = fields.Boolean(string="Is Favorite", compute='_compute_is_favorite', search='_search_is_favorite')
    bookmark_user_ids = fields.Many2many('res.users', 'km_article_bookmark_rel', 'article_id', 'user_id', string='Bookmarked By')
    
    @api.depends('favorite_user_ids')
    @api.depends_context('uid')
    def _compute_is_favorite(self):
        for article in self:
            article.is_favorite = self.env.user.id in article.favorite_user_ids.ids

    def _search_is_favorite(self, operator, value):
        if (operator == '=' and value) or (operator == '!=' and not value):
            return [('favorite_user_ids', 'in', self.env.user.id)]
        return [('favorite_user_ids', 'not in', self.env.user.id)]

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
            if not self.icon and hasattr(self.template_id, 'icon') and self.template_id.icon:
                self.icon = self.template_id.icon
            if not self.cover_image and hasattr(self.template_id, 'cover_image') and self.template_id.cover_image:
                self.cover_image = self.template_id.cover_image
                if hasattr(self.template_id, 'cover_position') and self.template_id.cover_position:
                    self.cover_position = self.template_id.cover_position

    
    expiration_date = fields.Date(string='Expiration Date', tracking=True)
    needs_review = fields.Boolean(string='Needs Review', default=False, tracking=True)
    reviewer_id = fields.Many2one('res.users', string='Reviewer', tracking=True, index=True)

    def _compute_website_url(self):
        """Compute the website URL for the article."""
        super(KnowledgeArticle, self)._compute_website_url()
        for article in self:
            article.website_url = '/my/knowledge/%s' % article.id

    def action_submit_review(self):
        """Submit the article for review."""
        self.write({'state': 'review'})

    def action_publish(self):
        """Publish the article."""
        self.write({'state': 'published', 'is_published': True})

    def action_archive(self):
        """Archive the article."""
        self.write({'state': 'archived'})

    @api.model
    def get_unsplash_keys(self):
        return {
            'access_key': self.env['ir.config_parameter'].sudo().get_param('knowledge_management_pro.unsplash_access_key'),
            'app_id': self.env['ir.config_parameter'].sudo().get_param('knowledge_management_pro.unsplash_app_id'),
        }

    def action_download_cover(self, url):
        """Download cover image from a given URL and set it on the article synchronously."""
        self.ensure_one()
        from urllib.parse import urlparse
        import socket
        import ipaddress
        
        try:
            parsed_url = urlparse(url)
            if parsed_url.scheme not in ('http', 'https'):
                _logger.warning(f"Invalid URL scheme: {parsed_url.scheme}")
                return False
            allowed_domains = ['images.unsplash.com', 'api.unsplash.com']
            if parsed_url.hostname not in allowed_domains:
                _logger.warning(f"Domain not allowed for SSRF protection: {parsed_url.hostname}")
                return False
                
            try:
                ip = socket.gethostbyname(parsed_url.hostname)
                if ipaddress.ip_address(ip).is_private or ipaddress.ip_address(ip).is_loopback:
                    _logger.warning(f"IP address {ip} not allowed for SSRF protection")
                    return False
            except socket.gaierror:
                _logger.warning(f"Could not resolve hostname {parsed_url.hostname}")
                return False

            response = requests.get(url, timeout=5, allow_redirects=False)
            response.raise_for_status()
            
            # Additional check: If Unsplash redirects, we don't follow it automatically.
            # 2xx status code indicates successful fetch of the image.
            image_base64 = base64.b64encode(response.content).decode('utf-8')
            self.write({
                'cover_image': image_base64,
                'cover_position': 50.0
            })
            return True
        except Exception as e:
            _logger.error(f"Failed to initiate cover download from URL {url}: {e}")
            return False

            
    def _recursively_change_state(self, state):
        """Recursively change the state of child articles."""
        if self.child_ids:
            # Updating child_ids triggers their own write() method, which natively propagates the state.
            self.child_ids.write({'state': state})
            
    @api.model_create_multi
    def create(self, vals_list):
        records = super(KnowledgeArticle, self).create(vals_list)
        now = fields.Datetime.now()
        versions_to_create = []
        for rec in records:
            versions_to_create.append({
                'article_id': rec.id,
                'version_number': 1,
                'user_id': self.env.user.id,
                'date': now,
                'title_snapshot': rec.name,
                'content_snapshot': rec.content,
                'change_summary': _("Initial version"),
                'change_type': 'create'
            })
        if versions_to_create:
            self.env['knowledge.management.version'].create(versions_to_create)
        return records

    def write(self, vals):
        """Update the article and conditionally create a version snapshot."""
        res = super(KnowledgeArticle, self).write(vals)
        if 'state' in vals:
            if vals['state'] in ['archived', 'draft']:
                for rec in self:
                    rec._recursively_change_state(vals['state'])
        
        # We only check for versions if this is a normal update, not a restore.
        # We will pass context 'skip_version_creation' during restore.
        if ('content' in vals or 'name' in vals) and not self.env.context.get('skip_version_creation'):
            now = fields.Datetime.now()
            # Batch fetch latest versions for all articles in self
            last_versions_data = self.env['knowledge.management.version']._read_group(
                [('article_id', 'in', self.ids)],
                ['article_id'],
                ['id:max']
            )
            version_ids = [v_id for article, v_id in last_versions_data]
            latest_versions = self.env['knowledge.management.version'].browse(version_ids)
            latest_version_by_article = {v.article_id.id: v for v in latest_versions}

            versions_to_create = []
            for article in self:
                last_version = latest_version_by_article.get(article.id)
                
                create_snapshot = False
                change_desc_parts = []
                
                if not last_version:
                    create_snapshot = True
                    change_desc_parts.append(_("Initial save"))
                else:
                    # Explicit change detection
                    if 'name' in vals and article.name != last_version.title_snapshot:
                        create_snapshot = True
                        change_desc_parts.append(_("Updated title"))
                    
                    if 'content' in vals and article.content != last_version.content_snapshot:
                        create_snapshot = True
                        change_desc_parts.append(_("Updated content"))
                        
                if create_snapshot:
                    version_num = (last_version.version_number + 1) if last_version else 1
                    versions_to_create.append({
                        'article_id': article.id,
                        'version_number': version_num,
                        'user_id': self.env.user.id,
                        'date': now,
                        'title_snapshot': article.name,
                        'content_snapshot': article.content,
                        'change_summary': ", ".join(change_desc_parts) if change_desc_parts else _("Updated"),
                        'change_type': 'update'
                    })
            
            if versions_to_create:
                # Removed sudo to enforce standard model permissions
                self.env['knowledge.management.version'].create(versions_to_create)
                _logger.info("Batch created %s version snapshots.", len(versions_to_create))

        return res

    def restore_version(self, version_id):
        self.ensure_one()
        version = self.env['knowledge.management.version'].browse(version_id)
        if not version.exists() or version.article_id.id != self.id:
            return False

        # First we update the article itself, but skip normal version creation
        self.with_context(skip_version_creation=True).write({
            'name': version.title_snapshot or self.name,
            'content': version.content_snapshot or ''
        })
        
        # Then we create a new revision denoting the restore
        last_version_data = self.env['knowledge.management.version'].search_read(
            [('article_id', '=', self.id)],
            ['version_number'],
            order='version_number desc',
            limit=1
        )
        version_num = (last_version_data[0]['version_number'] + 1) if last_version_data else 1
        
        self.env['knowledge.management.version'].create({
            'article_id': self.id,
            'version_number': version_num,
            'user_id': self.env.user.id,
            'date': fields.Datetime.now(),
            'title_snapshot': self.name,
            'content_snapshot': self.content,
            'change_summary': _("Restored from version %s") % version.version_number,
            'change_type': 'restore'
        })
        return True



    def action_move_to_trash(self):
        """Move the article and its children to the trash."""
        for article in self:
            article.write({
                'previous_parent_id': article.parent_id.id,
                'previous_sequence': article.sequence,
            })
        
        domain = ['|'] * (len(self) - 1) + [('parent_path', '=like', f'{article.parent_path}%') for article in self]
        if domain:
            descendants = self.search(domain)
            descendants.write({
                'active': False,
                'in_trash': True,
            })
        return True

    def action_restore_from_trash(self):
        """Restore the article from the trash to its previous parent if possible."""
        for article in self:
            vals = {
                'active': True,
                'in_trash': False,
            }
            prev_parent = article.previous_parent_id
            if prev_parent and prev_parent.exists() and not prev_parent.in_trash:
                vals['parent_id'] = prev_parent.id
                vals['sequence'] = article.previous_sequence or self.DEFAULT_RESTORE_SEQUENCE
            else:
                vals['parent_id'] = False
                vals['sequence'] = self.DEFAULT_RESTORE_SEQUENCE
                
            article.write(vals)

        domain = ['|'] * (len(self) - 1) + [('parent_path', '=like', f'{article.parent_path}%') for article in self]
        if domain:
            descendants = self.with_context(active_test=False).search(domain) - self
            if descendants:
                descendants.write({
                    'active': True,
                    'in_trash': False,
                })
        return True

    def action_permanent_delete(self):
        """Permanently delete the article and its children."""
        domain = ['|'] * (len(self) - 1) + [('parent_path', '=like', f'{article.parent_path}%') for article in self]
        if domain:
            descendants = self.with_context(active_test=False).search(domain)
            return descendants.unlink()
        return super(KnowledgeArticle, self).unlink()

    def action_toggle_lock(self):
        """Toggle the lock status of the article."""
        self.ensure_one()
        # You could add access checks here
        self.is_locked = not self.is_locked
        return self.is_locked

    def action_toggle_favorite(self):
        """Toggle the favorite status for the current user."""
        self.ensure_one()
        user_id = self.env.user.id
        if user_id in self.favorite_user_ids.ids:
            self.favorite_user_ids = [(3, user_id)]
            return False
        else:
            self.favorite_user_ids = [(4, user_id)]
            return True


    @api.model
    def move_article(self, article_id, new_parent_id, new_sequence=None):
        """Move an article to a new parent and update its sequence."""
        article = self.browse(article_id).exists()
        if not article:
            return False

        vals = {}
        if new_parent_id is not None:
            # Check for circular reference
            parent = self.browse(new_parent_id).exists() if new_parent_id else None
            curr = parent
            while curr:
                if curr.id == article.id:
                    raise ValidationError(_("Cannot move an article into itself or its children."))
                curr = curr.parent_id
            vals['parent_id'] = new_parent_id or False

        if new_sequence is not None:
            vals['sequence'] = new_sequence

        if vals:
            article.write(vals)
        return True

    def action_duplicate(self):
        """Duplicate the current article and its children."""
        self.ensure_one()
        return self._duplicate_recursive().id

    def _duplicate_recursive(self, parent_id=None):
        """Recursively duplicate the article and its children."""
        self.ensure_one()
        
        descendants = self.search([('parent_path', '=like', f'{self.parent_path}%')])
        id_mapping = {}
        sorted_descendants = descendants.sorted(key=lambda r: len(r.parent_path))
        
        top_new_record = None
        for record in sorted_descendants:
            is_top = (record.id == self.id)
            new_parent = parent_id if is_top else id_mapping.get(record.parent_id.id, False)
            
            default = {
                'parent_id': new_parent,
                'author_id': self.env.user.id,
            }
            if is_top and not parent_id:
                default['name'] = f"{record.name} (Copy)"
                
            new_record = record.copy(default=default)
            id_mapping[record.id] = new_record.id
            
            if is_top:
                top_new_record = new_record
                
        return top_new_record
