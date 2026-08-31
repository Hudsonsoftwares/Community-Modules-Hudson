# -*- coding: utf-8 -*-
from odoo import api, fields, models
from datetime import timedelta

class HelpdeskManagementSLA(models.Model):
    _name = 'helpdesk.management.sla'
    _description = 'Helpdesk SLA'
    _order = 'sequence, id'

    name = fields.Char(string='SLA Name', required=True)
    description = fields.Text('Description')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    
    team_id = fields.Many2one('helpdesk.management.team', string='Team', required=True)
    ticket_type_id = fields.Many2one('helpdesk.management.ticket.type', string='Ticket Type')
    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Urgent')
    ], string='Priority')
    stage_id = fields.Many2one('helpdesk.management.stage', string='Target Stage', required=True)
    
    target_type = fields.Selection([
        ('reaching_stage', 'Reaching Stage'),
        ('assign', 'Assigning Ticket')
    ], string='Target Type', default='reaching_stage', required=True)
    
    target_hours = fields.Float(string='Target Time (Hours)', required=True)
    exclude_stage_ids = fields.Many2many('helpdesk.management.stage', string='Excluding Stages')
    
    res_model = fields.Char(default='helpdesk.management.ticket')
    domain = fields.Char(string='Tickets', default='[]')
    
    def _compute_deadline(self, ticket):
        # Simplistic deadline calculation (could be improved with working calendar)
        return ticket.create_date + timedelta(hours=self.target_hours)
