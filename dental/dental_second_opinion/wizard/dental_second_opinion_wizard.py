# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError

from ..models.dental_second_opinion import DECISIONS


class DentalSecondOpinionWizard(models.TransientModel):
    """Captures the note (and decision) of a workflow step; the request method checks the user's role."""
    _name = 'dental.second.opinion.wizard'
    _description = 'Second Opinion Workflow Step'

    request_id = fields.Many2one('dental.second.opinion', string='Request', required=True, ondelete='cascade')
    action = fields.Selection([
        ('request_info', 'Request Information'),
        ('provide_info', 'Provide Information'),
        ('decline', 'Decline'),
        ('clarification', 'Request Clarification'),
        ('decision', 'Record Clinical Decision'),
    ], required=True)
    decision = fields.Selection(DECISIONS, string='Clinical Decision')
    note = fields.Text(string='Notes')
    info_request_note = fields.Text(related='request_id.info_request_note')

    def action_confirm(self):
        self.ensure_one()
        note = (self.note or '').strip()
        request = self.request_id
        if self.action == 'decision':
            if not self.decision:
                raise UserError(_('Choose the clinical decision.'))
            request.action_record_decision(self.decision, note)
            return {'type': 'ir.actions.act_window_close'}
        if not note:
            raise UserError(_('Please enter a note for the other clinician.'))
        method = {
            'request_info': request.action_request_info,
            'provide_info': request.action_provide_info,
            'decline': request.action_decline,
            'clarification': request.action_request_clarification,
        }[self.action]
        method(note)
        return {'type': 'ir.actions.act_window_close'}
