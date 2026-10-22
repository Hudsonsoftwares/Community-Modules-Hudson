import base64
import time
from odoo import http, _
from odoo.http import request
from odoo.http.stream import content_disposition
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
                ('access_ids.group_id', 'in', user.group_ids.ids)
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
            ('access_ids.group_id', 'in', user.group_ids.ids)
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
            'access_token': access_token or signature_req.access_token or '',
            'page_name': 'dms_signature',
        }
        return request.render("dms_enterprise_features.portal_signature_page", values)


    @http.route(['/dms/signature/<int:req_id>/pdf', '/dms/signature/<int:req_id>/<string:access_token>/pdf'], type='http', auth="public", website=True)
    def portal_dms_signature_pdf(self, req_id, access_token=None, **kw):
        """Serve the PDF content directly for public or authenticated signers."""
        token = access_token or kw.get('access_token')
        signature_req = request.env['dms.file.signature.request'].sudo().browse(req_id)
        if not signature_req.exists():
            return request.not_found()

        # Authorization: token match, or logged-in recipient, or internal user
        is_authorized = False
        if token and signature_req.access_token == token:
            is_authorized = True
        elif not request.env.user._is_public():
            if (signature_req.recipient_id == request.env.user or 
                    request.env.user.has_group('dms.group_dms_user') or 
                    request.env.is_admin()):
                is_authorized = True

        if not is_authorized:
            return request.not_found()

        # Get PDF content: if signed, pdf_content is the signed PDF; otherwise clean revision content for signer
        if signature_req.state == 'signed':
            raw_field = signature_req.pdf_content or (signature_req.revision_id and signature_req.revision_id.content)
        else:
            raw_field = (signature_req.revision_id and signature_req.revision_id.content) or signature_req.pdf_content
        if not raw_field:
            return request.not_found()

        # Extract raw binary bytes safely (handling bytes, BinaryValueAttachment, and base64 strings)
        content = None
        if hasattr(raw_field, '__bytes__') or isinstance(raw_field, (bytes, bytearray)):
            raw_bytes = bytes(raw_field)
            if raw_bytes.startswith(b'%PDF'):
                content = raw_bytes
            else:
                try:
                    decoded = base64.b64decode(raw_bytes)
                    content = decoded if decoded.startswith(b'%PDF') else raw_bytes
                except Exception:
                    content = raw_bytes
        elif isinstance(raw_field, str):
            try:
                content = base64.b64decode(raw_field.encode('ascii'))
            except Exception:
                content = raw_field.encode('utf-8')

        if not content:
            return request.not_found()

        filename = (signature_req.revision_id and (signature_req.revision_id.file_name or signature_req.revision_id.file_id.name)) or f"document_{signature_req.id}.pdf"
        headers = [
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', f'inline; filename="{filename}"'),
            ('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0'),
            ('Pragma', 'no-cache'),
            ('Expires', '0'),
        ]
        return request.make_response(content, headers)

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

    def _check_file_access(self, file_rec):
        """
        Determines (has_access, can_replace) based on share settings,
        ensuring link permissions, group permissions, and viewer/editor rules
        are strictly respected like in Enterprise.
        """
        if not file_rec or not file_rec.exists() or file_rec.is_trashed or not file_rec.active:
            return False, False

        user = request.env.user
        link_access = file_rec.share_link_access or 'none'

        # 1. When accessed via link, if link is explicitly set to 'viewer':
        # The link is strictly a Viewer link. can_replace is ALWAYS False!
        if link_access == 'viewer':
            return True, False

        # 2. When accessed via link, if link is explicitly set to 'editor':
        if link_access == 'editor':
            return True, not file_rec.is_locked

        # 3. link_access == 'none' (No public link access)
        if user._is_public():
            return False, False

        # Logged-in internal users:
        # Check explicit access rules (groups, partners, users, departments)
        user_access = file_rec.access_ids.filtered(
            lambda a: (a.user_id == user) or 
                      (a.partner_id == user.partner_id) or 
                      (a.group_id and a.group_id in user.groups_id) or
                      (a.department_id and hasattr(user, 'employee_id') and user.employee_id and a.department_id == user.employee_id.department_id)
        )
        if user_access:
            has_edit = any(a.perm_edit or a.perm_rename or a.perm_move for a in user_access)
            has_view = any(a.perm_view or a.perm_download for a in user_access)
            if has_edit:
                return True, not file_rec.is_locked
            elif has_view:
                return True, False
            else:
                return False, False

        # Document owner or DMS manager
        if file_rec.document_owner_id == user or file_rec.create_uid == user or user.has_group('dms.group_dms_manager'):
            return True, not file_rec.is_locked

        # Check internal users setting
        if file_rec.share_internal_access == 'editor':
            return True, not file_rec.is_locked
        elif file_rec.share_internal_access == 'viewer':
            return True, False

        return False, False

    # ── File Sharing Public Routes ─────────────────────────────────────────

    @http.route(['/dms/share/file/<string:access_token>'], type='http', auth="public", website=True)
    def portal_share_file_view(self, access_token, **kw):
        file_rec = request.env['dms.file'].sudo().search([('access_token', '=', access_token)], limit=1)
        has_access, can_replace = self._check_file_access(file_rec)
        if not has_access:
            return request.render("dms_enterprise_features.portal_share_file_page", {
                'has_access': False,
                'file': None,
                'res_company': request.env.company,
                'db_name': request.env.cr.dbname,
            })

        user = request.env.user
        is_locked = file_rec.is_locked
        locked_by_name = file_rec.locked_by.name if file_rec.locked_by else 'another user'

        size_bytes = file_rec.size or 0
        formatted_size = human_size(size_bytes) if size_bytes else '0 B'
        file_timestamp = int(file_rec.write_date.timestamp()) if file_rec.write_date else int(time.time())

        filename = (file_rec.current_revision_id.file_name if file_rec.current_revision_id else False) or file_rec.name or "document"
        mimetype = (file_rec.mimetype or '').lower()
        fname_lower = filename.lower()
        is_pdf = (mimetype == 'application/pdf' or fname_lower.endswith('.pdf'))
        is_image = (mimetype.startswith('image/') or fname_lower.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp')))
        is_video = (mimetype.startswith('video/') or fname_lower.endswith(('.mp4', '.webm', '.ogg', '.mov')))
        is_audio = (mimetype.startswith('audio/') or fname_lower.endswith(('.mp3', '.wav', '.ogg', '.m4a')))
        is_previewable = is_pdf or is_image or is_video or is_audio

        is_public = bool(user._is_public())
        user_name = user.name if not is_public else ''
        csrf_token = request.csrf_token() if request else ''

        company = file_rec.company_id or (request.env.company if request else False)
        company_logo_uri = None
        if company:
            try:
                from odoo.tools.image import image_data_uri
                if company.logo:
                    company_logo_uri = image_data_uri(company.logo)
            except Exception:
                company_logo_uri = None

        if request and request.session and not request.session.db:
            request.session.db = request.env.cr.dbname

        values = {
            'has_access': has_access,
            'can_replace': can_replace,
            'is_locked': is_locked,
            'locked_by': locked_by_name,
            'file': file_rec,
            'access_token': access_token,
            'formatted_file_size': formatted_size,
            'file_timestamp': file_timestamp,
            'res_company': company,
            'company_logo_uri': company_logo_uri,
            'upload_success': kw.get('upload_success') == '1',
            'is_pdf': is_pdf,
            'is_image': is_image,
            'is_video': is_video,
            'is_audio': is_audio,
            'is_previewable': is_previewable,
            'is_public': is_public,
            'user_name': user_name,
            'csrf_token': csrf_token,
            'db_name': request.env.cr.dbname,
        }
        return request.render("dms_enterprise_features.portal_share_file_page", values)

    @http.route(['/dms/share/file/<string:access_token>/download'], type='http', auth="public", website=True)
    def portal_share_file_download(self, access_token, **kw):
        file_rec = request.env['dms.file'].sudo().search([('access_token', '=', access_token)], limit=1)
        has_access, _ = self._check_file_access(file_rec)
        if not has_access:
            return request.not_found()

        content = self._extract_file_raw_content(file_rec)
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

    def _extract_file_raw_content(self, file_rec):
        if not file_rec:
            return b""
        val = False
        if file_rec.current_revision_id and file_rec.current_revision_id.content:
            val = file_rec.current_revision_id.content
        elif file_rec.content:
            val = file_rec.content

        if not val:
            if hasattr(file_rec, 'content_file') and file_rec.content_file:
                val = file_rec.content_file
            elif hasattr(file_rec, 'content_binary') and file_rec.content_binary:
                val = file_rec.content_binary
            elif hasattr(file_rec, 'attachment_id') and file_rec.attachment_id:
                val = file_rec.attachment_id.raw or file_rec.attachment_id.datas

        if not val:
            return b""

        # Odoo 20 BinaryValueAttachment / BinaryValue
        if hasattr(val, 'open'):
            try:
                return bytes(val)
            except Exception:
                pass
        if hasattr(val, 'content'):
            c = val.content
            if isinstance(c, (bytes, bytearray)):
                return bytes(c)
            val = c

        if isinstance(val, (bytes, bytearray)):
            raw = bytes(val)
            if raw.startswith((b'%PDF', b'\x89PNG', b'\xff\xd8\xff', b'GIF8', b'PK\x03\x04', b'\x1f\x8b', b'RIFF')):
                return raw
            try:
                decoded = base64.b64decode(raw, validate=True)
                if decoded:
                    return decoded
            except Exception:
                pass
            return raw

        if isinstance(val, str):
            try:
                return base64.b64decode(val.encode('ascii'))
            except Exception:
                return val.encode('utf-8')

        try:
            return bytes(val)
        except Exception:
            return b""

    @http.route(['/dms/share/file/<string:access_token>/preview'], type='http', auth="public", website=True)
    def portal_share_file_preview(self, access_token, **kw):
        file_rec = request.env['dms.file'].sudo().search([('access_token', '=', access_token)], limit=1)
        has_access, _ = self._check_file_access(file_rec)
        if not has_access:
            return request.not_found()

        content = self._extract_file_raw_content(file_rec)
        filename = (file_rec.current_revision_id.file_name if file_rec.current_revision_id else False) or file_rec.name or "document"
        mimetype = (file_rec.mimetype or '').lower()
        fname_lower = filename.lower()

        if fname_lower.endswith('.pdf') or mimetype == 'application/pdf':
            mimetype = 'application/pdf'
        elif fname_lower.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp')) or mimetype.startswith('image/'):
            if fname_lower.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp')):
                ext = fname_lower.split('.')[-1]
                mimetype = f'image/{ext if ext != "jpg" else "jpeg"}'
        elif not mimetype or mimetype in ('application/octet-stream', 'binary/octet-stream'):
            from odoo.tools.mimetypes import guess_mimetype
            mimetype = guess_mimetype(content) or 'application/octet-stream'

        headers = [
            ('Content-Type', mimetype),
            ('Content-Disposition', f'inline; filename="{filename}"'),
            ('X-Content-Type-Options', 'nosniff'),
            ('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0'),
            ('Pragma', 'no-cache'),
            ('Expires', '0'),
        ]
        return request.make_response(content, headers)

    @http.route(['/dms/share/file/<string:access_token>/replace'], type='http', auth="public", methods=['POST'], website=True, csrf=True)
    def portal_share_file_replace(self, access_token, **post):
        file_rec = request.env['dms.file'].sudo().search([('access_token', '=', access_token)], limit=1)
        has_access, can_replace = self._check_file_access(file_rec)
        if not has_access or not can_replace or file_rec.is_locked:
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

        return request.redirect(f'/dms/share/file/{access_token}?db={request.env.cr.dbname}&upload_success=1')

