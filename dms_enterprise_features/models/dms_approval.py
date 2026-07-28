# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models

class DMSApprovalWorkflow(models.Model):
    _name = "dms.approval.workflow"
    _description = "Document Approval Workflow"
    
    name = fields.Char(string="Name", required=True)
    step_ids = fields.One2many(
        comodel_name="dms.approval.step",
        inverse_name="workflow_id",
        string="Steps"
    )

class DMSApprovalStep(models.Model):
    _name = "dms.approval.step"
    _description = "Approval Step"
    _order = "sequence, id"

    workflow_id = fields.Many2one(
        comodel_name="dms.approval.workflow",
        string="Workflow",
        required=True,
        ondelete="cascade"
    )
    sequence = fields.Integer(string="Sequence", default=10)
    name = fields.Char(string="Step Name", required=True)
    approver_id = fields.Many2one(
        comodel_name="res.users",
        string="Approver",
        required=True
    )

class DMSFileApproval(models.Model):
    _name = "dms.file.approval"
    _description = "File Approval"
    _order = "create_date desc"
    
    revision_id = fields.Many2one(
        comodel_name="dms.file.revision",
        string="Revision",
        required=True,
        ondelete="cascade"
    )
    approver_id = fields.Many2one(
        comodel_name="res.users",
        string="Approver",
        required=True
    )
    status = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('request_changes', 'Requested Changes')
        ],
        string="Status",
        default="pending"
    )
    comments = fields.Text(string="Comments")
    date = fields.Datetime(string="Date")

    def action_approve(self):
        self.write({'status': 'approved', 'date': fields.Datetime.now()})
        for record in self:
            record.revision_id.file_id.check_approval_status()
        return True

    def action_reject(self):
        self.write({'status': 'rejected', 'date': fields.Datetime.now()})
        for record in self:
            record.revision_id.file_id.check_approval_status()
        return True

    def action_request_changes(self):
        self.write({'status': 'request_changes', 'date': fields.Datetime.now()})
        for record in self:
            record.revision_id.file_id.check_approval_status()
        return True
