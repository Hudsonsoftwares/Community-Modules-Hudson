# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError

class DMSFile(models.Model):
    _inherit = "dms.file"



    # Document Controller Fields
    directory_id = fields.Many2one(
        comodel_name="dms.directory",
        domain="[('permission_upload', '=', True)]",
        required=False,
    )
    document_number = fields.Char(
        string="Document Number",
        readonly=True,
        copy=False,
        default=lambda self: _('New')
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # The Search Panel often injects default_directory_id = False if "All" is selected in the sidebar.
        # This overrides our original action context and prevents autofill.
        # We manually recover it here from other context keys if it evaluates to False.
        if 'directory_id' in fields_list and not res.get('directory_id'):
            recovered_id = self.env.context.get('searchpanel_default_directory_id')
            
            # Fallback to active_id if we came from a directory form
            if not recovered_id and self.env.context.get('active_model') == 'dms.directory':
                recovered_id = self.env.context.get('active_id')
                
            if recovered_id:
                res['directory_id'] = recovered_id
        return res
    department_id = fields.Many2one(
        comodel_name="hr.department",
        string="Department"
    )
    document_owner_id = fields.Many2one(
        comodel_name="res.users",
        string="Document Owner",
        default=lambda self: self.env.user
    )
    confidentiality = fields.Selection(
        selection=[
            ('public', 'Public'),
            ('internal', 'Internal'),
            ('confidential', 'Confidential'),
            ('restricted', 'Restricted')
        ],
        string="Confidentiality",
        default='internal'
    )
    expiry_date = fields.Date(string="Expiry Date")
    notify_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Notify User",
        help="Person to notify before expiration."
    )
    notify_before_days = fields.Integer(
        string="Notify Before (Days)",
        default=7,
        help="Number of days prior to expiration to notify the user."
    )
    expiry_notification_sent = fields.Boolean(
        string="Expiration Notification Sent",
        default=False,
        copy=False
    )
    status = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('in_approval', 'In Approval'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('obsolete', 'Obsolete')
        ],
        string="Status",
        default='draft',
        tracking=True
    )

    # Trash Management
    is_trashed = fields.Boolean(
        string="In Trash",
        default=False,
        tracking=True
    )
    trash_date = fields.Datetime(
        string="Trash Date"
    )

    
    revision_ids = fields.One2many(
        comodel_name="dms.file.revision",
        inverse_name="file_id",
        string="Revisions",
        context={'active_test': False}
    )
    current_revision_id = fields.Many2one(
        comodel_name="dms.file.revision",
        string="Current Revision",
        readonly=True
    )
    workflow_id = fields.Many2one(
        comodel_name="dms.approval.workflow",
        string="Approval Workflow"
    )
    signature_needed = fields.Boolean(
        string="Signature Needed"
    )
    access_ids = fields.One2many(
        comodel_name="dms.file.access",
        inverse_name="file_id",
        string="Access Control"
    )



    def action_request_approval(self):
        for record in self:
            if not record.workflow_id:
                continue
            if not record.current_revision_id:
                continue
            
            # Clear pending approvals for this revision just in case
            self.env['dms.file.approval'].search([
                ('revision_id', '=', record.current_revision_id.id),
                ('status', '=', 'pending')
            ]).unlink()

            for step in record.workflow_id.step_ids:
                self.env['dms.file.approval'].create({
                    'revision_id': record.current_revision_id.id,
                    'approver_id': step.approver_id.id,
                    'status': 'pending'
                })
            record.status = 'in_approval'

    def action_setup_signatures(self):
        revision_ids = []
        for record in self:
            if record.mimetype and record.mimetype.startswith('image/'):
                raise UserError(_("Electronic signature is only supported for PDF documents. '%s' is an image.") % record.name)
            if record.mimetype and record.mimetype != 'application/pdf' and not record.name.lower().endswith('.pdf'):
                raise UserError(_("Electronic signature is only supported for PDF documents. '%s' is not a PDF.") % record.name)

            if not record.current_revision_id and record.content:
                revision = self.env['dms.file.revision'].create({
                    'file_id': record.id,
                    'version': '1.0',
                    'content': record.content,
                    'file_name': record.name,
                    'comments': 'Initial revision auto-created for signature setup.'
                })
                record.current_revision_id = revision.id
                
            if record.current_revision_id and record.current_revision_id.content:
                revision_ids.append(str(record.current_revision_id.id))
        
        if not revision_ids:
            raise UserError(_("Please upload a PDF document before setting up signatures."))
        
        return {
            'type': 'ir.actions.client',
            'tag': 'dms_signature_pdf_viewer',
            'target': 'current',
            'context': {
                'default_revision_ids': ','.join(revision_ids),
            }
        }

    def check_approval_status(self):
        for record in self:
            if not record.current_revision_id:
                continue
            approvals = self.env['dms.file.approval'].search([
                ('revision_id', '=', record.current_revision_id.id)
            ])
            if not approvals:
                continue
            
            if any(a.status == 'rejected' for a in approvals):
                record.status = 'rejected'
            elif any(a.status == 'request_changes' for a in approvals):
                record.status = 'draft' # Or whatever status signifies changes needed
            elif all(a.status == 'approved' for a in approvals):
                record.status = 'approved'
                # Optionally make current if not already
                record.current_revision_id.action_make_current()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('document_number', _('New')) == _('New'):
                vals['document_number'] = self.env['ir.sequence'].next_by_code('dms.file.document.number') or _('New')
            
            # Auto-assign to Dashboard if directory is empty (Odoo Enterprise behavior)
            if not vals.get('directory_id'):
                dashboard = self.env['dms.directory'].search([('name', '=', 'Dashboard')], limit=1)
                if not dashboard:
                    storage = self.env['dms.storage'].search([], limit=1)
                    if not storage:
                        raise UserError(_("No storage configured. Please create a storage first."))
                    dashboard = self.env['dms.directory'].create({
                        'name': 'Dashboard',
                        'is_root_directory': True,
                        'storage_id': storage.id,
                    })
                vals['directory_id'] = dashboard.id
        
        records = super().create(vals_list)
        for record in records:
            self.env['dms.file.log'].sudo().create({
                'name': record.name,
                'file_id': record.id,
                'action': 'create',
            })
        return records

    def write(self, vals):
        if not self.env.su and not self.env.user.has_group('dms.group_dms_manager'):
            for record in self:
                if 'name' in vals and not record.permission_rename:
                    raise AccessError(_("You do not have permission to rename this file."))
                if 'directory_id' in vals and not record.permission_move:
                    raise AccessError(_("You do not have permission to move this file."))
                if ('content' in vals or 'file' in vals or 'attachment_id' in vals) and not record.permission_edit:
                    raise AccessError(_("You do not have permission to edit this file."))
        res = super().write(vals)
        for record in self:
            self.env['dms.file.log'].sudo().create({
                'name': record.name,
                'file_id': record.id,
                'action': 'edit',
                'details': str(vals)
            })
        return res

    def action_send_to_trash(self):
        for record in self:
            record.write({
                'is_trashed': True,
                'trash_date': fields.Datetime.now(),
                'active': False
            })
        return True

    def action_restore(self):
        for record in self:
            record.write({
                'is_trashed': False,
                'trash_date': False,
                'active': True
            })
        return True

    def unlink(self):
        for record in self:
            self.env['dms.file.log'].sudo().create({
                'name': record.name,
                'file_id': False,
                'action': 'delete',
            })
            
        # Soft delete logic: if not in trash, send to trash instead.
        to_trash = self.filtered(lambda r: not r.is_trashed)
        if to_trash:
            to_trash.action_send_to_trash()
            
        to_delete = self - to_trash
        if to_delete:
            return super(DMSFile, to_delete).unlink()
        return True

    @api.model
    def _cron_empty_trash(self):
        # Get retention delay from settings, default to 30 days
        delay_days = int(self.env["ir.config_parameter"].sudo().get_param("dms_enterprise.trash_delay", 30))
        if delay_days < 0:
            return # Disabled
            
        from dateutil.relativedelta import relativedelta
        cutoff_date = fields.Datetime.now() - relativedelta(days=delay_days)
        
        expired_files = self.search([
            ('is_trashed', '=', True),
            ('trash_date', '<', cutoff_date)
        ])
        if expired_files:
            expired_files.unlink()
            
        expired_dirs = self.env['dms.directory'].search([
            ('is_trashed', '=', True),
            ('trash_date', '<', cutoff_date)
        ])
        if expired_dirs:
            expired_dirs.unlink()

    @api.model
    def _cron_process_expiries(self):
        today = fields.Date.context_today(self)
        
        # 1. Process Trashing
        # Files where expiry_date <= today and not yet trashed
        expired_files = self.search([
            ('expiry_date', '!=', False),
            ('expiry_date', '<=', today),
            ('is_trashed', '=', False)
        ])
        if expired_files:
            expired_files.action_send_to_trash()

        # 2. Process Notifications
        # Files that have an expiry_date, are not trashed, haven't been notified yet, and have a notify_user_id
        pending_notifications = self.search([
            ('expiry_date', '!=', False),
            ('is_trashed', '=', False),
            ('notify_user_id', '!=', False),
            ('expiry_notification_sent', '=', False)
        ])
        
        from datetime import timedelta
        for file in pending_notifications:
            notify_date = file.expiry_date - timedelta(days=file.notify_before_days or 0)
            if today >= notify_date:
                # Create a Next Activity (To-Do) for the user
                self.env['mail.activity'].create({
                    'res_id': file.id,
                    'res_model_id': self.env['ir.model']._get('dms.file').id,
                    'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                    'summary': _('Document Expiry Warning'),
                    'note': _('This document will expire on %s and will be moved to the Trash automatically.', file.expiry_date),
                    'user_id': file.notify_user_id.id,
                    'date_deadline': file.expiry_date,
                })
                file.write({'expiry_notification_sent': True})

    def action_open_form_view(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'dms.file',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }
