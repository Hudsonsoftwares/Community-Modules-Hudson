import base64
import time
from odoo import http, _
from odoo.http import request, content_disposition
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.exceptions import AccessError, MissingError
from odoo.tools import human_size

class DMSPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        user = request.env.user
        if 'dms_signature_count' in counters:
            values['dms_signature_count'] = request.env['dms.file.signature.request'].search_count([
                ('recipient_id', '=', user.id),
                ('state', 'in', ['sent', 'draft'])
            ])
        if 'dms_document_count' in counters:
            values['dms_document_count'] = request.env['dms.file'].sudo().search_count([
                ('is_trashed', '=', False),
                ('active', '=', True),
                '|', '|', '|',
                ('access_ids.partner_id', '=', user.partner_id.id),
                ('access_ids.user_id', '=', user.id),
                ('document_owner_id', '=', user.id),
                ('access_ids.group_id', 'in', user.groups_id.ids)
            ])
        return values

    @http.route(['/my/dms/documents', '/my/dms/documents/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_dms_documents(self, page=1, **kw):
        values = self._prepare_portal_layout_values()
        user = request.env.user
        domain = [
            ('is_trashed', '=', False),
            ('active', '=', True),
            '|', '|', '|',
            ('access_ids.partner_id', '=', user.partner_id.id),
            ('access_ids.user_id', '=', user.id),
            ('document_owner_id', '=', user.id),
            ('access_ids.group_id', 'in', user.groups_id.ids)
        ]
        files = request.env['dms.file'].sudo().search(domain, order='write_date desc')
        values.update({
            'files': files,
            'page_name': 'dms_documents',
            'default_url': '/my/dms/documents',
        })
        return request.render("dms_enterprise_features.portal_my_dms_documents", values)


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

        return_url = kw.get('return_url') or request.params.get('return_url')
        if return_url:
            redirect_url = return_url
        elif not request.env.user._is_public():
            file_id = signature_req.revision_id and signature_req.revision_id.file_id and signature_req.revision_id.file_id.id
            if file_id:
                redirect_url = f"/web#id={file_id}&model=dms.file&view_type=form"
            else:
                redirect_url = "/web#action=dms.action_dms_file"
        else:
            redirect_url = signature_req.get_portal_url()

        result = {
            'force_refresh': True,
            'redirect_url': redirect_url,
        }

        # Check for sequential "Sign Now" handoff
        if signature_req.is_sign_now:
            next_req = request.env['dms.file.signature.request'].sudo().search([
                ('revision_id', '=', signature_req.revision_id.id),
                ('state', '=', 'sent'),
                ('is_sign_now', '=', True),
                ('id', '!=', signature_req.id)
            ], order='id asc', limit=1)
            
            if next_req:
                result['next_signer_url'] = next_req.get_portal_url()
                result['next_signer_name'] = next_req.recipient_id.name

        return result

    # ── File Sharing Public Routes ─────────────────────────────────────────

    @http.route(['/dms/share/file/<string:access_token>'], type='http', auth="public", website=True)
    def portal_share_file_view(self, access_token, **kw):
        file_rec = request.env['dms.file'].sudo().search([('access_token', '=', access_token)], limit=1)
        if not file_rec or not file_rec.exists() or file_rec.is_trashed or not file_rec.active:
            return request.render("dms_enterprise_features.portal_share_file_page", {
                'has_access': False,
                'file': None,
                'res_company': request.env.company,
            })

        user = request.env.user
        link_access = file_rec.share_link_access or 'none'

        if not user._is_public():
            if file_rec.share_internal_access == 'editor':
                link_access = 'editor'
            elif file_rec.share_internal_access == 'viewer' and link_access != 'editor':
                link_access = 'viewer'

            # Check direct file access rules for this user or partner
            if file_rec.document_owner_id == user or file_rec.create_uid == user:
                link_access = 'editor'
            else:
                user_access = file_rec.access_ids.filtered(lambda a: (a.user_id == user) or (a.partner_id == user.partner_id))
                if user_access:
                    if any(a.perm_edit or a.perm_rename or a.perm_move for a in user_access):
                        link_access = 'editor'
                    elif any(a.perm_view or a.perm_download for a in user_access):
                        if link_access != 'editor':
                            link_access = 'viewer'

        has_access = (link_access in ['viewer', 'editor'])
        is_locked = file_rec.is_locked
        locked_by_name = file_rec.locked_by.name if file_rec.locked_by else 'another user'
        can_replace = (link_access == 'editor' and not is_locked)

        size_bytes = file_rec.size or 0
        formatted_size = human_size(size_bytes) if size_bytes else '0 B'
        file_timestamp = int(file_rec.write_date.timestamp()) if file_rec.write_date else int(time.time())

        values = {
            'has_access': has_access,
            'can_replace': can_replace,
            'is_locked': is_locked,
            'locked_by': locked_by_name,
            'file': file_rec,
            'access_token': access_token,
            'formatted_file_size': formatted_size,
            'file_timestamp': file_timestamp,
            'res_company': file_rec.company_id or request.env.company,
            'upload_success': kw.get('upload_success') == '1',
        }
        return request.render("dms_enterprise_features.portal_share_file_page", values)

    @http.route(['/dms/share/file/<string:access_token>/download'], type='http', auth="public", website=True)
    def portal_share_file_download(self, access_token, **kw):
        file_rec = request.env['dms.file'].sudo().search([('access_token', '=', access_token)], limit=1)
        if not file_rec or file_rec.is_trashed:
            return request.not_found()

        user = request.env.user
        link_access = file_rec.share_link_access or 'none'
        if not user._is_public():
            if file_rec.share_internal_access in ['viewer', 'editor']:
                link_access = file_rec.share_internal_access
            if file_rec.document_owner_id == user or file_rec.create_uid == user:
                link_access = 'editor'
            else:
                user_access = file_rec.access_ids.filtered(lambda a: (a.user_id == user) or (a.partner_id == user.partner_id))
                if user_access and any(a.perm_view or a.perm_download or a.perm_edit for a in user_access):
                    link_access = 'viewer'

        if link_access == 'none':
            return request.not_found()

        content_b64 = file_rec.current_revision_id.content or file_rec.content if file_rec.current_revision_id else file_rec.content
        content = base64.b64decode(content_b64) if content_b64 else b""
        filename = (file_rec.current_revision_id.file_name if file_rec.current_revision_id else False) or file_rec.name or "document"
        mimetype = file_rec.mimetype or 'application/octet-stream'

        headers = [
            ('Content-Type', mimetype),
            ('Content-Disposition', content_disposition(filename)),
            ('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0'),
            ('Pragma', 'no-cache'),
            ('Expires', '0'),
        ]
        return request.make_response(content, headers)

    @http.route(['/dms/share/file/<string:access_token>/preview'], type='http', auth="public", website=True)
    def portal_share_file_preview(self, access_token, **kw):
        file_rec = request.env['dms.file'].sudo().search([('access_token', '=', access_token)], limit=1)
        if not file_rec or file_rec.is_trashed:
            return request.not_found()

        user = request.env.user
        link_access = file_rec.share_link_access or 'none'
        if not user._is_public():
            if file_rec.share_internal_access in ['viewer', 'editor']:
                link_access = file_rec.share_internal_access
            if file_rec.document_owner_id == user or file_rec.create_uid == user:
                link_access = 'editor'
            else:
                user_access = file_rec.access_ids.filtered(lambda a: (a.user_id == user) or (a.partner_id == user.partner_id))
                if user_access and any(a.perm_view or a.perm_download or a.perm_edit for a in user_access):
                    link_access = 'viewer'

        if link_access == 'none':
            return request.not_found()

        content_b64 = file_rec.current_revision_id.content or file_rec.content if file_rec.current_revision_id else file_rec.content
        content = base64.b64decode(content_b64) if content_b64 else b""
        filename = (file_rec.current_revision_id.file_name if file_rec.current_revision_id else False) or file_rec.name or "document"
        mimetype = file_rec.mimetype or 'application/octet-stream'

        headers = [
            ('Content-Type', mimetype),
            ('Content-Disposition', f'inline; filename="{filename}"'),
            ('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0'),
            ('Pragma', 'no-cache'),
            ('Expires', '0'),
        ]
        return request.make_response(content, headers)

    @http.route(['/dms/share/file/<string:access_token>/replace'], type='http', auth="public", methods=['POST'], website=True, csrf=True)
    def portal_share_file_replace(self, access_token, **post):
        file_rec = request.env['dms.file'].sudo().search([('access_token', '=', access_token)], limit=1)
        if not file_rec or file_rec.is_trashed or file_rec.is_locked:
            return request.not_found()

        user = request.env.user
        can_replace = (file_rec.share_link_access == 'editor')
        if not user._is_public():
            if file_rec.share_internal_access == 'editor' or file_rec.document_owner_id == user or file_rec.create_uid == user:
                can_replace = True
            else:
                user_access = file_rec.access_ids.filtered(lambda a: (a.user_id == user) or (a.partner_id == user.partner_id))
                if user_access and any(a.perm_edit or a.perm_rename or a.perm_move for a in user_access):
                    can_replace = True

        if not can_replace:
            return request.not_found()

        replacement_file = post.get('replacement_file')
        if replacement_file:
            data = replacement_file.read()
            b64_content = base64.b64encode(data).decode('utf-8')
            new_filename = replacement_file.filename or file_rec.name
            user_label = request.env.user.name if not request.env.user._is_public() else "Public User"
            file_rec.with_context(
                revision_comment=f"Replaced via shared link ({user_label})"
            ).write({
                'content': b64_content,
                'name': new_filename,
            })

        return request.redirect(f'/dms/share/file/{access_token}?upload_success=1')

