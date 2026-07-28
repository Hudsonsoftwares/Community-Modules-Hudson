# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.exceptions import AccessError, MissingError

class DMSPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'dms_signature_count' in counters:
            values['dms_signature_count'] = request.env['dms.file.signature.request'].search_count([
                ('recipient_id', '=', request.env.user.id),
                ('state', 'in', ['sent', 'draft'])
            ])
        return values

    @http.route(['/my/dms/signatures', '/my/dms/signatures/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_dms_signatures(self, page=1, **kw):
        values = self._prepare_portal_layout_values()
        domain = [('recipient_id', '=', request.env.user.id), ('state', 'in', ['sent', 'draft'])]
        
        signatures = request.env['dms.file.signature.request'].search(domain)
        request.session['my_signatures_history'] = signatures.ids[:100]

        values.update({
            'signatures': signatures,
            'page_name': 'dms_signature',
            'default_url': '/my/dms/signatures',
        })
        return request.render("dms_enterprise_features.portal_my_dms_signatures", values)

    @http.route(['/my/dms/signature/<int:req_id>'], type='http', auth="user", website=True)
    def portal_my_dms_signature_detail(self, req_id, access_token=None, **kw):
        try:
            signature_req = self._document_check_access('dms.file.signature.request', req_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')

        if signature_req.recipient_id != request.env.user:
            return request.redirect('/my')

        values = {
            'signature_req': signature_req,
            'page_name': 'dms_signature',
        }
        return request.render("dms_enterprise_features.portal_signature_page", values)

    @http.route(['/my/dms/signature/<int:req_id>/accept'], type='json', auth="user", website=True)
    def portal_my_dms_signature_accept(self, req_id, access_token=None, name=None, signature=None):
        try:
            signature_req = self._document_check_access('dms.file.signature.request', req_id, access_token)
        except (AccessError, MissingError):
            return {'error': _('Invalid Request.')}

        if not signature:
            return {'error': _('Signature is missing.')}

        try:
            signature_req.process_signature(signature)
        except Exception as e:
            return {'error': str(e)}

        return {
            'force_refresh': True,
            'redirect_url': signature_req.get_portal_url(),
        }
