# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import http
from odoo.http import request
import json

class SignatureUIController(http.Controller):
    
    @http.route('/dms/signature/setup', type='http', auth='user', website=True)
    def signature_setup_ui(self, revision_ids=None, **kwargs):
        if not revision_ids:
            rev_ids = []
        else:
            rev_ids = [int(i) for i in revision_ids.split(',') if i.isdigit()]
            
        revisions = request.env['dms.file.revision'].browse(rev_ids)
            
        users = request.env['res.users'].search([('share', '=', False)])
        
        rev_data = [{'id': r.id, 'name': r.file_name or r.file_id.name, 'url': f'/web/content/dms.file.revision/{r.id}/content'} for r in revisions]
        
        values = {
            'revisions_json': json.dumps(rev_data),
            'users': users
        }
        return request.render('dms_enterprise_features.signature_setup_template', values)
        
    @http.route('/dms/signature/setup/upload', type='http', auth='user', methods=['POST'], csrf=False)
    def signature_setup_upload(self, file, **kwargs):
        file_content = file.read()
        file_name = file.filename
        
        # Create a temporary file in DMS or just add it to a "Signatures" directory
        # Let's find or create a default root directory
        directory = request.env['dms.directory'].search([], limit=1)
        if not directory:
            directory = request.env['dms.directory'].create({'name': 'Uploaded for Signature', 'is_root_directory': True})
            
        dms_file = request.env['dms.file'].create({
            'name': file_name,
            'directory_id': directory.id,
            'content': file_content
        })
        
        # Odoo DMS automatically creates a revision, get it
        revision = request.env['dms.file.revision'].search([('file_id', '=', dms_file.id)], order='id desc', limit=1)
        
        return json.dumps({
            'id': revision.id,
            'name': file_name,
            'url': f'/web/content/dms.file.revision/{revision.id}/content'
        })

    @http.route('/dms/signature/setup/save', type='json', auth='user', methods=['POST'])
    def signature_setup_save(self, payloads, roles_mapping, subject='', cc='', **kwargs):
        for payload in payloads:
            revision_id = payload.get('revision_id')
            boxes = payload.get('boxes', [])
            revision = request.env['dms.file.revision'].browse(revision_id)
            if not revision.exists():
                continue
                
            recipients = {}
            for box in boxes:
                role_id = box['recipient_id'] # e.g. "role_1"
                # get actual user id from mapping
                if role_id not in roles_mapping or not roles_mapping[role_id]:
                    continue # Skip if role is unassigned
                    
                rec_id = int(roles_mapping[role_id])
                if rec_id not in recipients:
                    recipients[rec_id] = []
                recipients[rec_id].append(box)
                
            for rec_id, items in recipients.items():
                req = request.env['dms.file.signature.request'].create({
                    'revision_id': revision.id,
                    'recipient_id': rec_id,
                    'state': 'sent' # Assuming sent immediately based on the standard flow
                })
                # Add CCs if needed, or handle email sending here using the subject/cc
                # request.env['mail.mail'].create(...)
                
                for item in items:
                    request.env['dms.file.signature.item'].create({
                        'request_id': req.id,
                        'item_type': item.get('type', 'signature'),
                        'page_number': int(item.get('page_number', 1)),
                        'pos_x': float(item.get('pos_x', 100)),
                        'pos_y': float(item.get('pos_y', 100)),
                        'width': float(item.get('width', 150)),
                        'height': float(item.get('height', 50)),
                    })
            
            revision.file_id.status = 'in_approval'
        return {'success': True}
