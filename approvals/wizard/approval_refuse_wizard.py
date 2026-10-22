# -*- coding: utf-8 -*-
from odoo import fields, models


class ApprovalRefuseWizard(models.TransientModel):
    _name = 'approval.refuse.wizard'
    _description = 'Reason for Refusal'

    request_id = fields.Many2one('approval.request', required=True)
    reason = fields.Text(string='Reason', required=True)

    def action_refuse(self):
        self.ensure_one()
        approver = self.request_id.approver_ids.filtered(
            lambda a: a.user_id == self.env.user and a.status == 'pending')
        approver.action_refuse()
        if self.reason:
            self.request_id.message_post(body=self.reason)
