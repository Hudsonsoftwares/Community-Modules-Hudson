# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models, _
from odoo.exceptions import UserError

class DMSFile(models.Model):
    _inherit = "dms.file"

    # Document Controller Fields
    document_number = fields.Char(
        string="Document Number",
        readonly=True,
        copy=False,
        default=lambda self: _('New')
    )
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

    
    revision_ids = fields.One2many(
        comodel_name="dms.file.revision",
        inverse_name="file_id",
        string="Revisions"
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('document_number', _('New')) == _('New'):
                # We will create a sequence for this
                vals['document_number'] = self.env['ir.sequence'].next_by_code('dms.file.document.number') or _('New')
        return super().create(vals_list)

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
        self.ensure_one()
        if not self.current_revision_id and self.content:
            # Auto-create the initial revision if user uploaded via native DMS UI
            revision = self.env['dms.file.revision'].create({
                'file_id': self.id,
                'version': '1.0',
                'content': self.content,
                'file_name': self.name,
                'comments': 'Initial revision auto-created for signature setup.'
            })
            self.current_revision_id = revision.id
            
        if not self.current_revision_id or not self.current_revision_id.content:
            raise UserError(_("Please upload a file before setting up signatures."))
        
        return {
            'type': 'ir.actions.client',
            'tag': 'dms_signature_pdf_viewer',
            'target': 'fullscreen',
            'context': {
                'default_file_id': self.id,
                'default_revision_id': self.current_revision_id.id,
            }
        }
        return True

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
        records = super().create(vals_list)
        for record in records:
            self.env['dms.file.log'].sudo().create({
                'name': record.name,
                'file_id': record.id,
                'action': 'create',
            })
        return records

    def write(self, vals):
        res = super().write(vals)
        for record in self:
            self.env['dms.file.log'].sudo().create({
                'name': record.name,
                'file_id': record.id,
                'action': 'edit',
                'details': str(vals)
            })
        return res

    def unlink(self):
        for record in self:
            self.env['dms.file.log'].sudo().create({
                'name': record.name,
                'file_id': False,
                'action': 'delete',
            })
        return super().unlink()
