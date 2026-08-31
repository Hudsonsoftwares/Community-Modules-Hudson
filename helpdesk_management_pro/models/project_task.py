# -*- coding: utf-8 -*-
from odoo import api, fields, models

class ProjectTask(models.Model):
    _inherit = 'project.task'

    helpdesk_ticket_id = fields.Many2one('helpdesk.management.ticket', string='Helpdesk Ticket', tracking=True)
