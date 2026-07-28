# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

import base64
from odoo import http, fields, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError

class FieldServicePortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'field_service_count' in counters:
            field_service_count = request.env['field.service.order'].search_count([])
            values['field_service_count'] = field_service_count
        return values

    @http.route(['/my/field_service', '/my/field_service/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_field_services(self, page=1, date_begin=None, date_end=None, sortby=None, **kw):
        values = self._prepare_portal_layout_values()
        FieldService = request.env['field.service.order']
        domain = []

        searchbar_sortings = {
            'date': {'label': _('Date'), 'order': 'create_date desc'},
            'name': {'label': _('Reference'), 'order': 'name'},
        }
        if not sortby:
            sortby = 'date'
        order = searchbar_sortings[sortby]['order']

        # count for pager
        order_count = FieldService.search_count(domain)
        # make pager
        pager = portal_pager(
            url="/my/field_service",
            url_args={'date_begin': date_begin, 'date_end': date_end, 'sortby': sortby},
            total=order_count,
            page=page,
            step=self._items_per_page
        )
        # search the count to display, according to the pager data
        orders = FieldService.search(domain, order=order, limit=self._items_per_page, offset=pager['offset'])

        values.update({
            'orders': orders,
            'page_name': 'field_service',
            'pager': pager,
            'default_url': '/my/field_service',
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby,
        })
        return request.render("hudson_field_service.portal_my_field_services", values)

    @http.route(['/my/field_service/<int:order_id>'], type='http', auth="public", website=True)
    def portal_my_field_service_order(self, order_id=None, access_token=None, **kw):
        try:
            order_sudo = self._document_check_access('field.service.order', order_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')

        values = self._field_service_order_get_page_view_values(order_sudo, access_token, **kw)
        return request.render("hudson_field_service.portal_my_field_service_order", values)

    @http.route(['/my/field_service/<int:order_id>/accept'], type='json', auth="public", website=True)
    def portal_my_field_service_order_accept(self, order_id, access_token=None, name=None, signature=None):
        try:
            order_sudo = self._document_check_access('field.service.order', order_id, access_token=access_token)
        except (AccessError, MissingError):
            return {'error': _('Invalid order.')}
            
        if not signature:
            return {'error': _('Signature is missing.')}
            
        order_sudo.write({
            'customer_signature': signature,
            'customer_signed_by': name,
            'customer_signed_date': fields.Datetime.now(),
        })
        
        # Generate the PDF and attach it to the order
        pdf_content, _ = request.env['ir.actions.report'].sudo()._render_qweb_pdf('hudson_field_service.action_report_field_service_order', [order_sudo.id])
        
        request.env['ir.attachment'].sudo().create({
            'name': f"{order_sudo.name}_signed_report.pdf",
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': 'field.service.order',
            'res_id': order_sudo.id,
            'mimetype': 'application/pdf',
        })
        
        return {
            'force_refresh': True,
            'redirect_url': order_sudo.get_portal_url(),
        }

    @http.route(['/my/field_service/<int:order_id>/timer/<string:action>'], type='http', auth="user", website=True)
    def portal_my_field_service_timer_action(self, order_id, action, access_token=None, **kw):
        try:
            order_sudo = self._document_check_access('field.service.order', order_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')

        # Verify they are a technician on this order
        is_technician = False
        if request.env.user:
            if order_sudo.employee_id.user_id == request.env.user:
                is_technician = True
            elif request.env.user in order_sudo.extra_employee_ids.mapped('user_id'):
                is_technician = True

        if not is_technician:
            return request.redirect(order_sudo.get_portal_url())

        if action in ['start', 'resume'] and not order_sudo.is_timer_running:
            if order_sudo.state == 'paused':
                order_sudo.action_resume_timer()
            else:
                order_sudo.action_start_timer()
        elif action in ['pause', 'stop'] and order_sudo.is_timer_running:
            now = fields.Datetime.now()
            duration_delta = now - order_sudo.timer_start
            duration_hours = duration_delta.total_seconds() / 3600.0
            
            request.env['field.service.timesheet'].sudo().create({
                'order_id': order_sudo.id,
                'user_id': order_sudo.employee_id.user_id.id or request.env.user.id,
                'date': fields.Date.context_today(order_sudo),
                'description': 'Portal timer session',
                'duration': duration_hours,
                'start_time': order_sudo.timer_start,
                'end_time': now,
            })
            
            if action == 'pause':
                order_sudo.write({
                    'timer_start': False,
                    'state': 'paused',
                    'last_paused_time': now,
                })
            else:
                order_sudo.write({
                    'timer_start': False,
                    'state': 'done',
                    'date_end': now,
                })
                close_stage = request.env['field.service.stage'].sudo().search(
                    [('is_close', '=', True)], limit=1
                )
                if close_stage:
                    order_sudo.stage_id = close_stage

        return request.redirect(order_sudo.get_portal_url())

    @http.route(['/my/field_service/<int:order_id>/add_product'], type='http', auth="user", website=True, methods=['POST'])
    def portal_my_field_service_add_product(self, order_id, product_id, quantity, access_token=None, **kw):
        try:
            order_sudo = self._document_check_access('field.service.order', order_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
            
        if not product_id or not quantity:
            return request.redirect(order_sudo.get_portal_url())
            
        order_sudo.write({
            'product_line_ids': [(0, 0, {
                'product_id': int(product_id),
                'quantity': float(quantity),
            })]
        })
        return request.redirect(order_sudo.get_portal_url())

    @http.route(['/my/field_service/<int:order_id>/add_photo'], type='http', auth="user", website=True, methods=['POST'])
    def portal_my_field_service_add_photo(self, order_id, photo, description='', access_token=None, **kw):
        try:
            order_sudo = self._document_check_access('field.service.order', order_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
            
        if photo:
            order_sudo.write({
                'service_image_ids': [(0, 0, {
                    'name': description or photo.filename,
                    'image': base64.b64encode(photo.read()),
                })]
            })
        return request.redirect(order_sudo.get_portal_url())

    @http.route(['/my/field_service/<int:order_id>/complete'], type='http', auth="user", website=True)
    def portal_my_field_service_complete(self, order_id, access_token=None, **kw):
        try:
            order_sudo = self._document_check_access('field.service.order', order_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
            
        if order_sudo.state in ['in_progress', 'paused'] and not order_sudo.is_timer_running:
            order_sudo.state = 'done'
            close_stage = request.env['field.service.stage'].sudo().search(
                [('is_close', '=', True)], limit=1
            )
            if close_stage:
                order_sudo.stage_id = close_stage
            
        return request.redirect(order_sudo.get_portal_url())

    @http.route(['/my/field_service/<int:order_id>/send_report'], type='http', auth="user", website=True)
    def portal_my_field_service_send_report(self, order_id, access_token=None, **kw):
        try:
            order_sudo = self._document_check_access('field.service.order', order_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
            
        template = request.env.ref('hudson_field_service.email_template_field_service_report', raise_if_not_found=False)
        if template:
            template.sudo().send_mail(order_sudo.id, force_send=True)
            
        url = order_sudo.get_portal_url()
        separator = '&' if '?' in url else '?'
        return request.redirect(url + separator + 'report_sent=1')

    def _field_service_order_get_page_view_values(self, order, access_token, **kwargs):
        is_technician = False
        if request.env.user:
            if order.employee_id.user_id == request.env.user:
                is_technician = True
            elif request.env.user in order.extra_employee_ids.mapped('user_id'):
                is_technician = True

        values = {
            'page_name': 'field_service',
            'order': order,
            'report_type': 'html',
            'is_technician': is_technician,
        }
        if is_technician:
            values['products'] = request.env['product.product'].sudo().search([('sale_ok', '=', True)])
        if access_token:
            values['no_breadcrumbs'] = True
            values['access_token'] = access_token
        
        if kwargs.get('error'):
            values['error'] = kwargs['error']
        if kwargs.get('warning'):
            values['warning'] = kwargs['warning']
        if kwargs.get('success'):
            values['success'] = kwargs['success']

        return values
