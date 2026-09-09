from odoo import api, fields, models
import json

class DmsSignatureSendWizard(models.TransientModel):
    _name = 'dms.signature.send.wizard'
    _description = 'Send Signature Request Wizard'

    subject = fields.Char('Subject', required=True, default='Signature Request')
    message = fields.Text('Message')
    cc = fields.Char('CC')
    valid_until = fields.Date('Valid Until')
    reminders = fields.Boolean('Reminders')
    reminder_days = fields.Integer('Reminder Days', default=7)
    hide_certificate_key = fields.Boolean('Hide Certificate Key')
    signing_order = fields.Boolean('Signing Order')
    is_sign_now = fields.Boolean('Is Sign Now')
    
    role_ids = fields.One2many('dms.signature.send.wizard.role', 'wizard_id', string='Roles')
    payload = fields.Text('Payload')

    has_multiple_roles = fields.Boolean(compute='_compute_has_multiple_roles')
    single_role_id = fields.Char('Single Role ID')
    single_signer_id = fields.Many2one('res.partner', string='Signer', domain="[('email', '!=', False)]")
    
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if res.get('is_sign_now'):
            res['single_signer_id'] = self.env.user.partner_id.id
            if res.get('role_ids'):
                # Also set it on the role if it's there
                for cmd in res['role_ids']:
                    if cmd[0] == 0:
                        cmd[2]['partner_id'] = self.env.user.partner_id.id
        return res
    
    @api.depends('role_ids')
    def _compute_has_multiple_roles(self):
        for wiz in self:
            wiz.has_multiple_roles = len(wiz.role_ids) > 1

    def action_confirm(self):
        self.ensure_one()
        payload_data = json.loads(self.payload)
        
        # Build role to partner_id mapping
        role_user_map = {}
        if self.has_multiple_roles:
            for role in self.role_ids:
                if not role.partner_id:
                    raise models.ValidationError("Please select a signer for all roles.")
                if not (role.partner_id.email or '').strip():
                    raise models.ValidationError(f"The contact '{role.partner_id.name}' must have an email address configured.")
                role_user_map[role.role_id] = str(role.partner_id.id)
        else:
            if not self.single_signer_id:
                raise models.ValidationError("Please select a signer.")
            if not (self.single_signer_id.email or '').strip():
                raise models.ValidationError(f"The contact '{self.single_signer_id.name}' must have an email address configured.")
            # Map the single role (if any) or fallback to 'signer1'
            role_id = self.single_role_id or (self.role_ids and self.role_ids[0].role_id) or 'signer1'
            role_user_map[role_id] = str(self.single_signer_id.id)
            
        payload_data['subject'] = self.subject
        payload_data['message'] = self.message or ''
        payload_data['cc'] = self.cc or ''
        payload_data['is_sign_now'] = self.is_sign_now
        payload_data['signingOrder'] = self.signing_order
        payload_data['reminders'] = self.reminders
        payload_data['reminderDays'] = self.reminder_days
        payload_data['validUntil'] = self.valid_until and self.valid_until.strftime('%Y-%m-%d') or False
        payload_data['hideCertificateKey'] = self.hide_certificate_key
        
        # Inject user mapping into items
        for doc in payload_data.get('documents', []):
            for item in doc.get('items', []):
                item['assigned_user_id'] = role_user_map.get(item['role_id'])
                
        # Call the existing backend method based on context
        if self.env.context.get('is_from_template'):
            payload_data['roleUserMap'] = role_user_map
            action = self.env['hudson.sign.template'].create_requests_from_ui(
                payload_data['template_id'], 
                payload_data
            )
        else:
            action = self.env['dms.file.signature.request'].create_from_ui(payload_data)
        
        if self.is_sign_now and action and isinstance(action, dict) and action.get('type') == 'ir.actions.act_url':
            return action

        file_id = False
        if payload_data.get('documents'):
            rev_id = payload_data['documents'][0].get('revision_id')
            if rev_id:
                rev = self.env['dms.file.revision'].browse(rev_id)
                if rev.exists() and rev.file_id:
                    file_id = rev.file_id.id

        if not self.is_sign_now:
            if self.has_multiple_roles:
                recipients = self.role_ids.mapped('partner_id.name')
            else:
                recipients = [self.single_signer_id.name or '']
            recipient_names = ", ".join(filter(None, recipients))
            
            mail_server_count = self.env['ir.mail_server'].sudo().search_count([])
            if not mail_server_count:
                notif_title = "Request Created (SMTP Server Required)"
                notif_type = "warning"
                success_msg = f"Signature request created for {recipient_names}, but no Outgoing Mail Server is configured. Please set up an SMTP server (e.g. Gmail/Outlook) in Settings > Technical > Outgoing Mail Servers to deliver emails."
            else:
                notif_title = "Request Sent"
                notif_type = "success"
                success_msg = f"Signature request sent successfully to {recipient_names}." if recipient_names else "Signature request sent successfully."
            
            next_action = {
                'type': 'ir.actions.act_window',
                'res_model': 'dms.file',
                'res_id': file_id,
                'views': [[False, 'form']],
                'target': 'main',
            } if file_id else {'type': 'ir.actions.act_window_close'}
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': notif_title,
                    'message': success_msg,
                    'type': notif_type,
                    'sticky': not mail_server_count,
                    'next': next_action
                }
            }

        if file_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'dms.file',
                'res_id': file_id,
                'views': [[False, 'form']],
                'target': 'main',
            }
        return {'type': 'ir.actions.act_window_close'}

class DmsSignatureSendWizardRole(models.TransientModel):
    _name = 'dms.signature.send.wizard.role'
    _description = 'Signature Request Wizard Role'

    wizard_id = fields.Many2one('dms.signature.send.wizard', ondelete='cascade')
    role_id = fields.Char('Role ID')
    role_name = fields.Char('Role Name')
    partner_id = fields.Many2one('res.partner', string='Signer', domain="[('email', '!=', False)]")
    sequence = fields.Integer('Sequence')
