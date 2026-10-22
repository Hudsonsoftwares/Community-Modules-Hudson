# -*- coding: utf-8 -*-
# pyrefly: ignore [missing-import]
from odoo import api, fields, models, _


class ApprovalApprover(models.Model):
    _name = 'approval.approver'
    _description = 'Approval Approver'
    _order = 'sequence, id'
    _rec_name = 'user_id'

    request_id = fields.Many2one(
        'approval.request', string='Approval Request',
        required=True, ondelete='cascade')
    user_id = fields.Many2one(
        'res.users', string='Approver', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    status = fields.Selection([
        ('new', 'New'),
        ('pending', 'To Approve'),
        ('approved', 'Approved'),
        ('refused', 'Refused'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='new', required=True)
    required = fields.Boolean(string='Required Approver', default=True)
    is_manager = fields.Boolean(string='Is Manager Approval')
    date = fields.Datetime(string='Decision Date')

    def action_approve(self):
        for approver in self:
            approver.write({'status': 'approved', 'date': fields.Datetime.now()})
            approver.request_id.message_post(
                body=_('%s approved this request.') % approver.user_id.name)
            activities = approver.request_id.activity_ids.filtered(lambda a: a.user_id == approver.user_id)
            if activities:
                activities.action_feedback(feedback=_('Approved'))
            approver.request_id._check_approval_status()

    def action_refuse(self):
        for approver in self:
            approver.write({'status': 'refused', 'date': fields.Datetime.now()})
            approver.request_id.message_post(
                body=_('%s refused this request.') % approver.user_id.name)
            activities = approver.request_id.activity_ids.filtered(lambda a: a.user_id == approver.user_id)
            if activities:
                activities.action_feedback(feedback=_('Refused'))
            approver.request_id._check_approval_status()
