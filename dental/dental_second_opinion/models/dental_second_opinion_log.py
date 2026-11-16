# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError

from .dental_second_opinion import STATES


class DentalSecondOpinionLog(models.Model):
    """Append-only audit trail of a second opinion request.

    Rows are created by the workflow (with sudo) and can never be edited or deleted; they are
    removed only together with their draft request.
    """
    _name = 'dental.second.opinion.log'
    _description = 'Second Opinion Audit History'
    _order = 'date desc, id desc'

    request_id = fields.Many2one('dental.second.opinion', string='Request', required=True, index=True,
                                 ondelete='cascade', readonly=True)
    company_id = fields.Many2one(related='request_id.company_id', store=True, index=True)
    date = fields.Datetime(string='Date', default=fields.Datetime.now, required=True, readonly=True)
    user_id = fields.Many2one('res.users', string='By', required=True, readonly=True)
    event = fields.Selection([
        ('created', 'Request created'),
        ('submitted', 'Sent to specialist'),
        ('review_started', 'Review started'),
        ('info_requested', 'Information requested'),
        ('info_provided', 'Information provided'),
        ('declined', 'Declined by specialist'),
        ('opinion_submitted', 'Opinion submitted'),
        ('opinion_revised', 'Opinion revised'),
        ('clarification_requested', 'Clarification requested'),
        ('decision_recorded', 'Clinical decision recorded'),
        ('cancelled', 'Cancelled'),
        ('reset_to_draft', 'Reset to draft'),
    ], string='Event', required=True, readonly=True)
    state_from = fields.Selection(STATES, string='From', readonly=True)
    state_to = fields.Selection(STATES, string='To', readonly=True)
    note = fields.Text(string='Details', readonly=True)

    def write(self, vals):
        raise UserError(_('The second opinion audit history cannot be modified.'))

    def unlink(self):
        raise UserError(_('The second opinion audit history cannot be deleted.'))
