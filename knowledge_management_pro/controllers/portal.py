from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError

class KnowledgePortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'knowledge_count' in counters:
            domain = [('state', '=', 'published'), ('is_published', '=', True)]
            values['knowledge_count'] = request.env['knowledge.management.article'].search_count(domain)
        return values

    @http.route(['/my/knowledge', '/my/knowledge/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_knowledge(self, page=1, **kw):
        values = self._prepare_portal_layout_values()
        
        domain = [('state', '=', 'published'), ('is_published', '=', True)]
        
        article_count = request.env['knowledge.management.article'].search_count(domain)
        pager = portal_pager(
            url="/my/knowledge",
            total=article_count,
            page=page,
            step=self._items_per_page
        )
        
        articles = request.env['knowledge.management.article'].search(
            domain, limit=self._items_per_page, offset=pager['offset']
        )
        
        values.update({
            'articles': articles,
            'page_name': 'knowledge',
            'pager': pager,
            'default_url': '/my/knowledge',
        })
        return request.render("knowledge_management_pro.portal_my_knowledge", values)

    @http.route(['/my/knowledge/<int:article_id>'], type='http', auth="user", website=True)
    def portal_article_page(self, article_id, **kw):
        try:
            article = request.env['knowledge.management.article'].browse(article_id)
            
            # This triggers access rule checks
            article.check_access_rule('read')
            
            if not article.exists() or article.state != 'published' or not article.is_published:
                return request.redirect('/my/knowledge')
                
            has_write_access = False
            try:
                article.check_access_rule('write')
                has_write_access = article.check_access_rights('write', raise_exception=False)
            except AccessError:
                pass
                
            values = {
                'article': article,
                'page_name': 'knowledge',
                'has_write_access': has_write_access,
            }
            return request.render("knowledge_management_pro.portal_article_page", values)
        except AccessError:
            return request.redirect('/my/knowledge')
            
    @http.route(['/my/knowledge/<int:article_id>/edit'], type='http', auth="user", website=True, methods=['POST'])
    def portal_article_edit(self, article_id, **post):
        try:
            article = request.env['knowledge.management.article'].browse(article_id)
            article.check_access_rule('write')
            if not article.check_access_rights('write', raise_exception=False):
                raise AccessError(_("You don't have write access."))
                
            if not article.exists() or article.state != 'published' or not article.is_published:
                return request.redirect('/my/knowledge')
                
            content = post.get('content')
            if content:
                article.sudo().write({'content': content})
                
            return request.redirect('/my/knowledge/%s' % article_id)
        except AccessError:
            return request.redirect('/my/knowledge')
