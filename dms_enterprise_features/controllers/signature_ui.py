# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import http
from odoo.http import request

class SignatureUIController(http.Controller):
    
    @http.route('/dms/signature/setup/<int:revision_id>', type='http', auth='user', website=True)
    def signature_setup_ui(self, revision_id, **kwargs):
        revision = request.env['dms.file.revision'].browse(revision_id)
        if not revision.exists():
            return request.not_found()
            
        users = request.env['res.users'].search([('share', '=', False)])
        
        values = {
            'revision': revision,
            'pdf_url': f'/web/content/dms.file.revision/{revision.id}/content',
            'users': users
        }
        return request.render('dms_enterprise_features.signature_setup_template', values)

    @http.route('/dms/signature/setup/save', type='json', auth='user', methods=['POST'])
    def signature_setup_save(self, revision_id, boxes, **kwargs):
        revision = request.env['dms.file.revision'].browse(revision_id)
        if not revision.exists():
            return {'error': 'Revision not found'}
            
        for box in boxes:
            request.env['dms.file.signature.request'].create({
                'revision_id': revision.id,
                'recipient_id': int(box['recipient_id']),
                'pos_x': float(box['pos_x']),
                'pos_y': float(box['pos_y']),
                'page_number': int(box['page_number']),
                'state': 'draft'
            })
            
        revision.file_id.status = 'in_approval'
        return {'success': True}
