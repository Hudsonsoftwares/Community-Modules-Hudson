from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64

class HudsonSignTemplate(models.Model):
    _name = "hudson.sign.template"
    _description = "Signature Template"

    name = fields.Char(string="Template Name", required=True)
    attachment_id = fields.Many2one("ir.attachment", string="PDF Document", required=True)
    active = fields.Boolean(default=True)
    author_id = fields.Many2one("res.users", string="Author", default=lambda self: self.env.user)
    
    tag_ids = fields.Many2many('hudson.sign.template.tag', string="Tags")

    role_ids = fields.One2many("hudson.sign.template.role", "template_id", string="Roles")
    sign_item_ids = fields.One2many("hudson.sign.template.item", "template_id", string="Signature Fields")
    
    # Statistics
    request_ids = fields.One2many("dms.file.signature.request", "template_id", string="Requests")
    count_in_progress = fields.Integer(compute="_compute_counts", string="In Progress")
    count_signed = fields.Integer(compute="_compute_counts", string="Signed")

    @api.model
    def create_template_from_file(self, file_name, file_content):
        if not file_name.lower().endswith('.pdf'):
            raise UserError(_("Only PDF files are supported."))
            
        decoded_data = file_content
        if isinstance(file_content, str):
            try:
                decoded_data = base64.b64decode(file_content)
            except Exception:
                decoded_data = file_content

        attach_vals = {
            'name': file_name,
            'type': 'binary',
            'mimetype': 'application/pdf'
        }
        if 'raw' in self.env['ir.attachment']._fields:
            attach_vals['raw'] = decoded_data
        else:
            attach_vals['datas'] = file_content
        attachment = self.env['ir.attachment'].create(attach_vals)
        
        template = self.env['hudson.sign.template'].create({
            'name': file_name.rsplit('.', 1)[0],
            'attachment_id': attachment.id
        })
        
        return template.action_open_builder()

    @api.depends('request_ids.state')
    def _compute_counts(self):
        for template in self:
            template.count_in_progress = len(template.request_ids.filtered(lambda r: r.state in ['draft', 'sent']))
            template.count_signed = len(template.request_ids.filtered(lambda r: r.state == 'signed'))

    def _get_sign_directory(self):
        sign_dir = self.env['dms.directory'].search([('name', '=', 'Sign')], limit=1)
        if not sign_dir:
            storage = self.env['dms.storage'].search([], limit=1)
            if not storage:
                raise UserError(_("No DMS Storage found. Please configure Document Management System."))
            sign_dir = self.env['dms.directory'].create({
                'name': 'Sign',
                'is_root_directory': True,
                'storage_id': storage.id,
            })
        return sign_dir

    def _create_signature_requests(self, role_user_map):
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_("Please attach a PDF document to this template."))
            
        sign_dir = self._get_sign_directory()
        
        # Use a unique name to avoid 'file already exists in this directory' errors
        from datetime import datetime
        unique_suffix = datetime.now().strftime('%Y%m%d%H%M%S')
        file_name = f"{self.name} - Signature Request - {unique_suffix}"
        
        pdf_data = self.attachment_id.raw if hasattr(self.attachment_id, 'raw') and self.attachment_id.raw else getattr(self.attachment_id, 'datas', False)
        new_file = self.env['dms.file'].sudo().create({
            'name': file_name,
            'directory_id': sign_dir.id,
            'content': pdf_data,
            'mimetype': self.attachment_id.mimetype or 'application/pdf',
            'extension': 'pdf'
        })
        
        revision = self.env['dms.file.revision'].sudo().create({
            'file_id': new_file.id,
            'version': '1.0',
            'content': new_file.content,
            'file_name': new_file.name,
            'comments': 'Initial revision for signature request.'
        })
        new_file.sudo().write({'current_revision_id': revision.id})
        
        sign_request = self.env['hudson.sign.request'].create({
            'revision_id': revision.id,
            'template_id': self.id,
        })
        
        requests = self.env['dms.file.signature.request']
        
        for role_id, user_id in role_user_map.items():
            role = self.env['hudson.sign.template.role'].browse(role_id)
            user = self.env['res.users'].browse(user_id)
            
            # Find items for this role
            role_items = self.sign_item_ids.filtered(lambda i: i.role_id.id == role.id)
            
            req = self.env['dms.file.signature.request'].create({
                'revision_id': revision.id,
                'recipient_id': user.id,
                'template_id': self.id,
                'state': 'sent',
                'hudson_request_id': sign_request.id,
            })
            requests += req
            
            item_vals = []
            for item in role_items:
                dms_type = item.type_id.item_type if item.type_id else 'signature'
                item_vals.append({
                    'request_id': req.id,
                    'item_type': dms_type,
                    'page_number': item.page_number,
                    'pos_x': item.pos_x,
                    'pos_y': item.pos_y,
                    'width': item.width,
                    'height': item.height,
                    'mandatory': item.mandatory
                })
                
            if item_vals:
                self.env['dms.file.signature.item'].create(item_vals)
                
        return requests

    def action_send(self):
        # Auto-create a default role if none exists
        if not self.role_ids:
            self.env['hudson.sign.template.role'].create({
                'name': 'Signer',
                'template_id': self.id
            })
            
        wizard = self.env['hudson.sign.send.request.wizard'].create({
            'template_id': self.id,
        })
        
        # Pre-populate roles in wizard
        for role in self.role_ids:
            self.env['hudson.sign.send.request.wizard.role'].create({
                'wizard_id': wizard.id,
                'role_id': role.id,
            })
            
        return {
            'name': _('Send Signature Request'),
            'type': 'ir.actions.act_window',
            'res_model': 'hudson.sign.send.request.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_sign_now(self):
        # Simplified for 1 user
        if not self.role_ids:
            role = self.env['hudson.sign.template.role'].create({
                'name': 'Signer',
                'template_id': self.id
            })
        else:
            role = self.role_ids[0]
            
        role_map = {role.id: self.env.user.id}
        requests = self._create_signature_requests(role_map)
        
        if not requests:
            raise UserError(_("No signature request generated."))
            
        # Redirect to the first request (assuming 1 for sign now)
        req = requests[0]
        return {
            'type': 'ir.actions.act_url',
            'url': f'/my/signature/{req.id}/{req.access_token}',
            'target': 'self',
        }

    @api.model
    def create_requests_from_ui(self, template_id, data):
        template = self.browse(template_id)
        role_map = data.get('roleUserMap', {})
        
        clean_role_map = {}
        for role_id, user_val in role_map.items():
            if not user_val:
                continue
            # Use the same logic as DMS module: resolve or create portal user from email/name
            user_id = self.env['dms.file.signature.request']._get_or_create_user(str(user_val).strip())
            if not user_id:
                raise UserError(_(f"Could not find or create user for '{user_val}'."))
            clean_role_map[int(role_id)] = user_id
            
        is_sign_now = data.get('isSignNow', False)
        
        requests = template._create_signature_requests(clean_role_map)
        
        if not requests:
            raise UserError(_("No signature request generated."))
        
        # Check if subject field exists on the model before writing
        sig_request_fields = self.env['dms.file.signature.request'].fields_get()
        
        for req in requests:
            write_vals = {}
            if 'subject' in sig_request_fields:
                write_vals['subject'] = data.get('subject', '')
            if 'message' in sig_request_fields:
                write_vals['message'] = data.get('message', '')
            if 'valid_until' in sig_request_fields and data.get('validUntil'):
                write_vals['valid_until'] = data.get('validUntil')
            if write_vals:
                req.write(write_vals)
                
            if not is_sign_now:
                try:
                    req.send_signature_email()
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Failed to send email for request {req.id}: {e}")
                
        if is_sign_now:
            req = requests[0]
            return {
                'type': 'ir.actions.act_url',
                'url': f'/my/signature/{req.id}/{req.access_token}',
                'target': 'self',
            }
        return False

    def action_share(self):
        pass
        
    def action_open_builder(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'hudson_sign.template_builder',
            'name': _('Template Builder'),
            'context': {
                'active_id': self.id,
                'active_model': 'hudson.sign.template'
            }
        }

class HudsonSignTemplateRole(models.Model):
    _name = "hudson.sign.template.role"
    _description = "Template Role"
    
    name = fields.Char(string="Role Name", required=True)
    template_id = fields.Many2one("hudson.sign.template", required=True, ondelete="cascade")
    color = fields.Char(string="Color", default="#e6f2eb")

class HudsonSignTemplateItem(models.Model):
    _name = "hudson.sign.template.item"
    _description = "Signature Template Item"

    template_id = fields.Many2one("hudson.sign.template", required=True, ondelete="cascade")
    type_id = fields.Many2one("hudson.sign.item.type", string="Field Type", required=True)
    role_id = fields.Many2one("hudson.sign.template.role", string="Role")
    
    page_number = fields.Integer(string="Page Number", required=True, default=1)
    pos_x = fields.Float(string="X Position", required=True, default=100.0)
    pos_y = fields.Float(string="Y Position", required=True, default=100.0)
    width = fields.Float(string="Width", default=150.0)
    height = fields.Float(string="Height", default=50.0)
    
    mandatory = fields.Boolean(string="Mandatory", default=True)

class HudsonSignSendRequestWizard(models.TransientModel):
    _name = "hudson.sign.send.request.wizard"
    _description = "Send Signature Request Wizard"

    template_id = fields.Many2one("hudson.sign.template", required=True)
    message = fields.Text(string="Message")
    role_mapping_ids = fields.One2many("hudson.sign.send.request.wizard.role", "wizard_id", string="Signers")

    def action_send_request(self):
        role_map = {}
        for mapping in self.role_mapping_ids:
            if not mapping.user_id:
                raise UserError(_(f"Please assign a user for role '{mapping.role_id.name}'"))
            role_map[mapping.role_id.id] = mapping.user_id.id
            
        requests = self.template_id._create_signature_requests(role_map)
        for req in requests:
            req.send_signature_email()
            
        return {'type': 'ir.actions.act_window_close'}

class HudsonSignSendRequestWizardRole(models.TransientModel):
    _name = "hudson.sign.send.request.wizard.role"
    _description = "Role Mapping for Send Wizard"
    
    wizard_id = fields.Many2one("hudson.sign.send.request.wizard", required=True, ondelete="cascade")
    role_id = fields.Many2one("hudson.sign.template.role", required=True, readonly=True)
    user_id = fields.Many2one("res.users", string="Contact / User")

class HudsonSignTemplateUploadWizard(models.TransientModel):
    _name = "hudson.sign.template.upload.wizard"
    _description = "Upload Template Wizard"
    
    file_content = fields.Binary(string="PDF Document", required=True)
    file_name = fields.Char(string="File Name", required=True)
    
    def action_upload(self):
        if not self.file_name.lower().endswith('.pdf'):
            raise UserError(_("Only PDF files are supported."))
            
        attach_vals = {
            'name': self.file_name,
            'type': 'binary',
            'mimetype': 'application/pdf'
        }
        if 'raw' in self.env['ir.attachment']._fields:
            attach_vals['raw'] = self.file_content
        else:
            attach_vals['datas'] = self.file_content
        attachment = self.env['ir.attachment'].create(attach_vals)
        
        template = self.env['hudson.sign.template'].create({
            'name': self.file_name.rsplit('.', 1)[0],
            'attachment_id': attachment.id
        })
        
        return template.action_open_builder()
