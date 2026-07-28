# -*- coding: utf-8 -*-
from odoo import models, fields

class MrpEcoType(models.Model):
    _name = 'mrp.eco.type'
    _description = 'ECO Type'
    _order = 'sequence, id'

    name = fields.Char('Name', required=True, translate=True)
    sequence = fields.Integer('Sequence', default=1)
    
    eco_ids = fields.One2many('mrp.eco', 'type_id', string='ECOs')
    eco_count = fields.Integer('ECO Count', compute='_compute_eco_count')

    def _compute_eco_count(self):
        for record in self:
            record.eco_count = len(record.eco_ids)
    color = fields.Integer('Color')
