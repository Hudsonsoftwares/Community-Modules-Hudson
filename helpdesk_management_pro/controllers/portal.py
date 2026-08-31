# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

class HelpdeskManagementPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'ticket_count' in counters:
            ticket_count = request.env['helpdesk.management.ticket'].search_count([
                ('partner_id', '=', request.env.user.partner_id.id)
            ])
            values['ticket_count'] = ticket_count
        return values

    @http.route(['/my/tickets', '/my/tickets/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_tickets(self, page=1, **kw):
        values = self._prepare_portal_layout_values()
        partner = request.env.user.partner_id
        Ticket = request.env['helpdesk.management.ticket']
        
        domain = [('partner_id', '=', partner.id)]
        ticket_count = Ticket.search_count(domain)
        
        pager = portal_pager(
            url="/my/tickets",
            total=ticket_count,
            page=page,
            step=self._items_per_page
        )
        
        tickets = Ticket.search(domain, limit=self._items_per_page, offset=pager['offset'])
        
        values.update({
            'tickets': tickets,
            'page_name': 'ticket',
            'pager': pager,
            'default_url': '/my/tickets',
        })
        return request.render("helpdesk_management_pro.portal_my_tickets", values)

    @http.route(['/my/ticket/<int:ticket_id>'], type='http', auth="user", website=True)
    def portal_my_ticket_detail(self, ticket_id=None, **kw):
        ticket = request.env['helpdesk.management.ticket'].browse(ticket_id)
        if ticket.partner_id != request.env.user.partner_id:
            return request.redirect('/my')
        
        values = {
            'ticket': ticket,
            'page_name': 'ticket',
        }
        return request.render("helpdesk_management_pro.portal_ticket_page", values)

    @http.route(['/helpdesk/submit'], type='http', auth="public", website=True)
    def helpdesk_submit(self, **kwargs):
        categories = request.env['helpdesk.management.category'].sudo().search([])
        return request.render("helpdesk_management_pro.helpdesk_submit_ticket", {
            'categories': categories,
        })

    @http.route(['/helpdesk/submit/process'], type='http', auth="public", methods=['POST'], website=True)
    def helpdesk_submit_process(self, **kwargs):
        vals = {
            'subject': kwargs.get('subject'),
            'description': kwargs.get('description'),
            'category_id': int(kwargs.get('category_id')) if kwargs.get('category_id') else False,
            'partner_name': kwargs.get('name'),
            'partner_email': kwargs.get('email'),
        }
        
        if request.env.user != request.env.ref('base.public_user'):
            vals['partner_id'] = request.env.user.partner_id.id
            
        ticket = request.env['helpdesk.management.ticket'].sudo().create(vals)
        return request.redirect('/helpdesk/submit/success?ticket=%s' % ticket.name)

    @http.route(['/helpdesk/submit/success'], type='http', auth="public", website=True)
    def helpdesk_submit_success(self, **kwargs):
        return request.render("helpdesk_management_pro.helpdesk_submit_success", {
            'ticket_name': kwargs.get('ticket'),
        })

    @http.route(['/helpdesk/rating/<int:ticket_id>/<string:token>/<int:rating>'], type='http', auth="public", website=True)
    def helpdesk_rating(self, ticket_id, token, rating, **kwargs):
        ticket = request.env['helpdesk.management.ticket'].sudo().browse(ticket_id)
        if not ticket.exists() or ticket.access_token != token:
            return request.not_found()
            
        if rating not in (1, 3, 5):
            rating = 3
            
        # Create rating
        request.env['helpdesk.management.ticket.rating'].sudo().create({
            'ticket_id': ticket.id,
            'rating': str(rating),
            'feedback': 'Rating provided via email link.'
        })
        
        return request.render("helpdesk_management_pro.helpdesk_rating_success", {
            'ticket': ticket,
            'rating': rating,
        })
