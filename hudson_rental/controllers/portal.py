# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import http, fields, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError


class RentalPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'rental_count' in counters:
            rental_count = request.env['rental.order'].search_count([])
            values['rental_count'] = rental_count
        return values

    @http.route(['/my/rentals', '/my/rentals/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_rentals(self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None, **kw):
        values = self._prepare_portal_layout_values()
        RentalOrder = request.env['rental.order']
        
        domain = []
        
        searchbar_sortings = {
            'date': {'label': _('Order Date'), 'order': 'date_order desc'},
            'name': {'label': _('Reference'), 'order': 'name'},
            'pickup': {'label': _('Pickup Date'), 'order': 'pickup_date desc'},
        }
        
        searchbar_filters = {
            'all': {'label': _('All'), 'domain': []},
            'draft': {'label': _('Quotation'), 'domain': [('state', '=', 'draft')]},
            'confirmed': {'label': _('Confirmed'), 'domain': [('state', '=', 'confirmed')]},
            'active': {'label': _('Active'), 'domain': [('state', 'in', ['reserved', 'picked_up'])]},
            'returned': {'label': _('Returned'), 'domain': [('state', 'in', ['returned', 'done'])]},
        }
        
        if not sortby:
            sortby = 'date'
        order = searchbar_sortings[sortby]['order']
        
        if not filterby:
            filterby = 'all'
        domain += searchbar_filters[filterby]['domain']
        
        # Count for pager
        rental_count = RentalOrder.search_count(domain)
        
        # Pager
        pager = portal_pager(
            url="/my/rentals",
            url_args={'date_begin': date_begin, 'date_end': date_end, 'sortby': sortby, 'filterby': filterby},
            total=rental_count,
            page=page,
            step=self._items_per_page
        )
        
        # Search
        rentals = RentalOrder.search(domain, order=order, limit=self._items_per_page, offset=pager['offset'])
        
        values.update({
            'rentals': rentals,
            'page_name': 'rental',
            'pager': pager,
            'default_url': '/my/rentals',
            'searchbar_sortings': searchbar_sortings,
            'searchbar_filters': searchbar_filters,
            'sortby': sortby,
            'filterby': filterby,
        })
        return request.render("hudson_rental.portal_my_rentals", values)

    @http.route(['/my/rentals/<int:order_id>'], type='http', auth="public", website=True)
    def portal_rental_order(self, order_id, access_token=None, **kw):
        try:
            order_sudo = self._document_check_access('rental.order', order_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        
        values = {
            'order': order_sudo,
            'page_name': 'rental',
            'report_type': 'html',
        }
        
        if access_token:
            values['no_breadcrumbs'] = True
            values['access_token'] = access_token
        
        return request.render("hudson_rental.portal_rental_order", values)

    @http.route(['/my/rentals/<int:order_id>/extend'], type='http', auth="user", website=True, methods=['POST'])
    def portal_rental_extend(self, order_id, new_return_date, access_token=None, **kw):
        try:
            order_sudo = self._document_check_access('rental.order', order_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        
        if order_sudo.state in ['picked_up']:
            new_date = fields.Datetime.from_string(new_return_date)
            if new_date > order_sudo.return_date:
                order_sudo.write({'return_date': new_date})
                # Recalculate pricing
                for line in order_sudo.order_line_ids:
                    line._onchange_price_unit()
        
        return request.redirect(f'/my/rentals/{order_id}')

    def _get_rental_searchbar_inputs(self):
        return {
            'all': {'input': 'all', 'label': _('Search in All')},
            'name': {'input': 'name', 'label': _('Search in Reference')},
            'product': {'input': 'product', 'label': _('Search in Products')},
        }

    def _rental_get_page_view_values(self, order, access_token, **kwargs):
        values = {
            'page_name': 'rental',
            'order': order,
        }
        return self._get_page_view_values(order, access_token, values, 'rental_history', False, **kwargs)
