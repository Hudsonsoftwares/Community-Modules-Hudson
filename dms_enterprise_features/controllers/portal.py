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

    @http.route(['/dms/signature/<int:req_id>/<string:access_token>'], type='http', auth="public", website=True)
    def portal_dms_signature_token(self, req_id, access_token, **kw):
        """Public route for signers clicking the email link (no login required)."""
        signature_req = request.env['dms.file.signature.request'].sudo().browse(req_id)
        if not signature_req.exists() or signature_req.access_token != access_token:
            # If user is logged in, find their latest pending signature or redirect to signatures list
            if not request.env.user._is_public():
                latest_sig = request.env['dms.file.signature.request'].sudo().search([
                    ('recipient_id', '=', request.env.user.id),
                    ('state', 'in', ['sent', 'draft'])
                ], order='id desc', limit=1)
                if latest_sig:
                    return request.redirect(f'/dms/signature/{latest_sig.id}/{latest_sig.access_token}')
                return request.redirect('/my/dms/signatures')
            return request.not_found()
        values = {
            'signature_req': signature_req,
            'access_token': access_token,
            'page_name': 'dms_signature',
        }
        return request.render("dms_enterprise_features.portal_signature_page", values)

    @http.route(['/my/dms/signature/<int:req_id>'], type='http', auth="public", website=True)
    def portal_my_dms_signature_detail(self, req_id, access_token=None, **kw):
        try:
            signature_req = self._document_check_access('dms.file.signature.request', req_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')

        if not access_token and signature_req.recipient_id != request.env.user:
            return request.redirect('/my')

        values = {
            'signature_req': signature_req,
            'access_token': access_token or '',
            'page_name': 'dms_signature',
        }
        return request.render("dms_enterprise_features.portal_signature_page", values)


    @http.route(['/my/dms/signature/<int:req_id>/accept'], type='json', auth="public", website=True)
    def portal_my_dms_signature_accept(self, req_id, items_data=None, access_token=None, **kw):
        try:
            signature_req = self._document_check_access('dms.file.signature.request', req_id, access_token)
        except (AccessError, MissingError):
            return {'error': _('Invalid Request.')}

        if not items_data:
            return {'error': _('Missing form data.')}

        try:
            for item_id, data in items_data.items():
                item = request.env['dms.file.signature.item'].sudo().browse(int(item_id))
                if item.request_id.id != signature_req.id:
                    continue
                
                vals = {'state': 'completed'}
                if 'value_text' in data:
                    vals['value_text'] = data['value_text']
                if 'value_bool' in data:
                    vals['value_bool'] = data['value_bool']
                if 'value_image' in data:
                    # expects base64 string without data prefix
                    vals['value_image'] = data['value_image'].split(',')[1] if ',' in data['value_image'] else data['value_image']
                    
                item.write(vals)
                
            signature_req.sudo().action_apply_signature()
        except Exception as e:
            return {'error': str(e)}

        return {
            'force_refresh': True,
            'redirect_url': signature_req.get_portal_url(),
        }
