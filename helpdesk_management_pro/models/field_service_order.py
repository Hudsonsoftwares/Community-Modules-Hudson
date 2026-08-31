# -*- coding: utf-8 -*-
from odoo import api, fields, models

class FieldServiceOrder(models.Model):
    _inherit = 'field.service.order'

    helpdesk_ticket_id = fields.Many2one('helpdesk.management.ticket', string='Helpdesk Ticket', tracking=True)
