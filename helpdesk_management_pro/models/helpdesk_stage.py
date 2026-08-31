# -*- coding: utf-8 -*-
from odoo import api, fields, models

class HelpdeskManagementStage(models.Model):
    _name = 'helpdesk.management.stage'
    _description = 'Helpdesk Stage'
    _order = 'sequence, id'

    name = fields.Char(string='Stage Name', required=True, translate=True)
    sequence = fields.Integer(default=10)
    is_close = fields.Boolean(string='Closing Stage', help="Tickets in this stage are considered closed.")
    fold = fields.Boolean(string='Folded in Kanban', help="This stage is folded in the kanban view by default.")
    
    team_ids = fields.Many2many('helpdesk.management.team', string='Teams',
                                help="Specific teams that uses this stage. Other teams will not be able to see or use this stage.")
    
    template_id = fields.Many2one('mail.template', string='Email Template',
                                  help="If set, an email will be sent to the customer when the ticket reaches this step.")
