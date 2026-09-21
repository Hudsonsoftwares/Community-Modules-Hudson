# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KnowledgeArticle(models.Model):
    _name = 'knowledge.management.article'
    _description = 'Knowledge Article'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, id'
    _parent_name = 'parent_id'
    _parent_store = True

    # ── Core Fields ──────────────────────────────────────────────────
    name = fields.Char(
        string='Article Name',
        default='Untitled',
        required=True,
        tracking=True,
    )
    icon = fields.Char(string='Icon', default='📄')
    cover_image_url = fields.Text(string='Cover Image URL')
    cover_position = fields.Char(string='Cover Position', default='50%')
    body_html = fields.Html(
        string='Body',
        sanitize=False,
        strip_style=False,
    )
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True, tracking=True)

    # ── Hierarchy ─────────────────────────────────────────────────────
    parent_id = fields.Many2one(
        'knowledge.management.article',
        string='Parent Article',
        index=True,
        ondelete='cascade',
    )
    child_ids = fields.One2many(
        'knowledge.management.article',
        'parent_id',
        string='Child Articles',
    )
    parent_path = fields.Char(index=True, unaccent=False)
    child_count = fields.Integer(
        string='Children',
        compute='_compute_child_count',
        store=False,
    )

    # ── Visibility ────────────────────────────────────────────────────
    visibility = fields.Selection([
        ('workspace', 'Workspace'),
        ('shared', 'Shared'),
        ('private', 'Private'),
    ], string='Visibility', default='workspace', required=True, tracking=True)

    # ── Favorites ─────────────────────────────────────────────────────
    favorite_user_ids = fields.Many2many(
        'res.users',
        'knowledge_article_favorite_rel',
        'article_id',
        'user_id',
        string='Favorited By',
    )
    is_user_favorite = fields.Boolean(
        string='Is Favorite',
        compute='_compute_is_user_favorite',
        inverse='_inverse_is_user_favorite',
    )

    # ── Sharing / Members ─────────────────────────────────────────────
    member_ids = fields.One2many(
        'knowledge.management.article.member',
        'article_id',
        string='Members',
    )

    # ── Options ──────────────────────────────────────────────────────
    is_locked = fields.Boolean(string='Locked', default=False, tracking=True)
    full_width = fields.Boolean(string='Full Width', default=False)
    is_article_item = fields.Boolean(
        string='Is Article Item',
        default=False,
        tracking=True,
        help='True if this article represents an item in an embedded list/kanban view, hidden from the sidebar menu',
    )

    # ── Items (for embedded kanban/list/calendar) ─────────────────────
    article_item_ids = fields.One2many(
        'knowledge.management.item',
        'article_id',
        string='Article Items',
    )
    version_ids = fields.One2many(
        'knowledge.management.article.version',
        'article_id',
        string='History Versions',
    )

    # ── Computed ─────────────────────────────────────────────────────
    @api.depends('child_ids', 'child_ids.active', 'child_ids.is_article_item')
    def _compute_child_count(self):
        for rec in self:
            rec.child_count = len(rec.child_ids.filtered(lambda c: c.active and not c.is_article_item))

    @api.depends('favorite_user_ids')
    def _compute_is_user_favorite(self):
        for rec in self:
            rec.is_user_favorite = self.env.user in rec.favorite_user_ids

    def _inverse_is_user_favorite(self):
        for rec in self:
            if rec.is_user_favorite:
                rec.favorite_user_ids = [(4, self.env.uid)]
            else:
                rec.favorite_user_ids = [(3, self.env.uid)]

    # ── Actions ──────────────────────────────────────────────────────
    def action_set_favorite(self):
        """Toggle favorite status for current user (frontend compatibility)."""
        self.ensure_one()
        user = self.env.user
        is_fav = user in self.favorite_user_ids
        if is_fav:
            self.write({'favorite_user_ids': [(3, user.id)]})
            return False
        else:
            self.write({'favorite_user_ids': [(4, user.id)]})
            return True

    def action_toggle_favorite(self):
        return self.action_set_favorite()

    def action_toggle_lock(self):
        self.ensure_one()
        self.is_locked = not self.is_locked

    def action_move_to_trash(self):
        for rec in self:
            rec.active = False
            # Also deactivate all child articles recursively
            children = self.search([('parent_id', '=', rec.id)])
            if children:
                children.action_move_to_trash()

    def action_restore_from_trash(self):
        self.ensure_one()
        self.active = True

    def action_create_copy(self):
        self.ensure_one()
        new_name = _('Copy of %s') % self.name
        copy = self.copy({'name': new_name})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'knowledge.management.article',
            'res_id': copy.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    # ── Version History & Lifecycle Methods ───────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('parent_id') and not vals.get('visibility'):
                parent = self.browse(vals['parent_id'])
                if parent.exists() and parent.visibility:
                    vals['visibility'] = parent.visibility
        return super(KnowledgeArticle, self).create(vals_list)

    def write(self, vals):
        # Auto-snapshot before saving new body_html if content is changing
        if 'body_html' in vals or 'name' in vals:
            for rec in self:
                if rec.body_html and (vals.get('body_html') != rec.body_html or vals.get('name') != rec.name):
                    rec._check_and_create_version_snapshot()
        res = super(KnowledgeArticle, self).write(vals)
        if 'visibility' in vals:
            for rec in self:
                children = self.search([('parent_id', '=', rec.id)])
                if children:
                    children.write({'visibility': vals['visibility']})
        return res

    def _check_and_create_version_snapshot(self):
        self.ensure_one()
        Version = self.env['knowledge.management.article.version']
        last = Version.search([('article_id', '=', self.id)], order='create_date desc, id desc', limit=1)
        # Create a new version if no version yet, or last version was more than 3 minutes ago
        now = fields.Datetime.now()
        if not last or (now - last.create_date).total_seconds() > 180:
            Version.create({
                'article_id': self.id,
                'name': self.name or 'Untitled',
                'body_html': self.body_html or '',
                'user_id': self.env.user.id,
            })

    def create_version_snapshot(self):
        """Create explicit version snapshot."""
        self.ensure_one()
        Version = self.env['knowledge.management.article.version']
        v = Version.create({
            'article_id': self.id,
            'name': self.name or 'Untitled',
            'body_html': self.body_html or '',
            'user_id': self.env.user.id,
        })
        return v.id

    def get_version_history(self):
        """Return history timeline entries for frontend matching Image 1."""
        self.ensure_one()
        versions = self.version_ids.sorted(key=lambda v: (v.create_date or fields.Datetime.now(), v.id), reverse=True)
        # Always make sure current state is in history
        if not versions and self.body_html:
            self.create_version_snapshot()
            versions = self.version_ids.sorted(key=lambda v: (v.create_date or fields.Datetime.now(), v.id), reverse=True)

        res = []
        for v in versions:
            user = v.user_id or self.env.user
            dt = v.create_date or fields.Datetime.now()
            res.append({
                'id': v.id,
                'name': v.name,
                'body_html': v.body_html or '',
                'user_id': user.id,
                'user_name': user.name,
                'user_avatar': '/web/image/res.users/%d/avatar_128' % user.id,
                'create_date_iso': dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'formatted_date': dt.strftime('%b %d, %Y at %I:%M:%S %p'),
            })
        return res

    def action_restore_version(self, version_id):
        """Restore article to a past version snapshot."""
        self.ensure_one()
        version = self.env['knowledge.management.article.version'].browse(version_id)
        if not version.exists() or version.article_id.id != self.id:
            return False
        # Create a snapshot of the current state before overwriting
        self.create_version_snapshot()
        self.write({
            'name': version.name,
            'body_html': version.body_html,
        })
        return True

    @api.model
    def get_sidebar_articles(self):
        """Return structured sidebar data for the Knowledge client action."""
        user = self.env.user
        domain_active = [('active', '=', True), ('is_article_item', '=', False)]

        def _serialize(articles):
            result = []
            for art in articles:
                result.append({
                    'id': art.id,
                    'name': art.name,
                    'icon': art.icon or '📄',
                    'visibility': art.visibility,
                    'is_user_favorite': user in art.favorite_user_ids,
                    'is_locked': art.is_locked,
                    'child_count': len(art.child_ids.filtered(lambda c: c.active and not c.is_article_item)),
                    'sequence': art.sequence,
                    'write_uid': {
                        'id': art.write_uid.id,
                        'name': art.write_uid.name,
                        'avatar': '/web/image/res.users/%d/avatar_128' % art.write_uid.id,
                    } if art.write_uid else None,
                    'write_date': art.write_date.strftime('%Y-%m-%dT%H:%M:%SZ') if art.write_date else False,
                })
            return result

        favorites = self.search(domain_active + [
            ('favorite_user_ids', 'in', [user.id]),
        ], order='sequence, id')

        workspace = self.search(domain_active + [
            ('visibility', '=', 'workspace'),
            ('parent_id', '=', False),
        ], order='sequence, id')

        shared = self.search(domain_active + [
            ('visibility', '=', 'shared'),
            ('parent_id', '=', False),
        ], order='sequence, id')

        private = self.search(domain_active + [
            ('visibility', '=', 'private'),
            ('parent_id', '=', False),
            ('create_uid', '=', user.id),
        ], order='sequence, id')

        return {
            'favorites': _serialize(favorites),
            'workspace': _serialize(workspace),
            'shared': _serialize(shared),
            'private': _serialize(private),
        }

    @api.model
    def get_article_children(self, parent_id):
        """Return children of a given article for sidebar lazy loading."""
        children = self.search([
            ('parent_id', '=', parent_id),
            ('active', '=', True),
            ('is_article_item', '=', False),
        ], order='sequence, id')
        user = self.env.user
        return [{
            'id': art.id,
            'name': art.name,
            'icon': art.icon or '📄',
            'visibility': art.visibility,
            'is_user_favorite': user in art.favorite_user_ids,
            'is_locked': art.is_locked,
            'child_count': len(art.child_ids.filtered(lambda c: c.active and not c.is_article_item)),
            'sequence': art.sequence,
            'write_uid': {
                'id': art.write_uid.id,
                'name': art.write_uid.name,
                'avatar': '/web/image/res.users/%d/avatar_128' % art.write_uid.id,
            } if art.write_uid else None,
            'write_date': art.write_date.strftime('%Y-%m-%dT%H:%M:%SZ') if art.write_date else False,
        } for art in children]

    @api.model
    def get_top_article(self):
        """Return the ID of the topmost article to auto-open."""
        user = self.env.user
        # First try favorites
        fav = self.search([
            ('active', '=', True),
            ('favorite_user_ids', 'in', [user.id]),
        ], order='sequence, id', limit=1)
        if fav:
            return fav.id
        # Then workspace
        ws = self.search([
            ('active', '=', True),
            ('visibility', '=', 'workspace'),
        ], order='sequence, id', limit=1)
        if ws:
            return ws.id
        # Then any
        any_art = self.search([('active', '=', True)], order='sequence, id', limit=1)
        return any_art.id if any_art else False

    @api.model
    def get_article_data(self):
        """Return full article data for the frontend.
        Can be called via orm.call with active_id in context.
        """
        article_id = self._context.get('active_id')
        if article_id:
            self = self.browse(article_id)
        self.ensure_one()
        user = self.env.user
        return {
            'id': self.id,
            'name': self.name,
            'icon': self.icon or '📄',
            'cover_image_url': self.cover_image_url or False,
            'cover_position': self.cover_position or '50%',
            'body_html': self.body_html or '',
            'visibility': self.visibility,
            'is_locked': self.is_locked,
            'full_width': self.full_width,
            'is_user_favorite': user in self.favorite_user_ids,
            'write_uid': {
                'id': self.write_uid.id,
                'name': self.write_uid.name,
                'avatar': '/web/image/res.users/%d/avatar_128' % self.write_uid.id,
            } if self.write_uid else None,
            'write_date': self.write_date.strftime('%Y-%m-%dT%H:%M:%SZ') if self.write_date else False,
            'parent_id': self.parent_id.id if self.parent_id else False,
            'parent_name': self.parent_id.name if self.parent_id else False,
        }

