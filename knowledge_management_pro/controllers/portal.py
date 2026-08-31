from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

class KnowledgePortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'knowledge_count' in counters:
            shares = request.env['knowledge.management.share'].sudo().search([
                ('user_id', '=', request.env.user.id)
            ])
            article_ids = shares.mapped('article_id.id')
            values['knowledge_count'] = len(article_ids)
        return values

    @http.route(['/my/knowledge', '/my/knowledge/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_knowledge(self, page=1, **kw):
        values = self._prepare_portal_layout_values()
        
        shares = request.env['knowledge.management.share'].sudo().search([
            ('user_id', '=', request.env.user.id)
        ])
        article_ids = shares.mapped('article_id.id')
        
        domain = [('id', 'in', article_ids)]
        
        article_count = request.env['knowledge.management.article'].sudo().search_count(domain)
        pager = portal_pager(
            url="/my/knowledge",
            total=article_count,
            page=page,
            step=self._items_per_page
        )
        
        articles = request.env['knowledge.management.article'].sudo().search(
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
        share = request.env['knowledge.management.share'].sudo().search([
            ('user_id', '=', request.env.user.id),
            ('article_id', '=', article_id)
        ], limit=1)
        
        if not share:
            return request.redirect('/my/knowledge')
            
        article = request.env['knowledge.management.article'].sudo().browse(article_id)
        
        if not article.exists():
            return request.redirect('/my/knowledge')
            
        values = {
            'article': article,
            'page_name': 'knowledge',
        }
        return request.render("knowledge_management_pro.portal_article_page", values)
