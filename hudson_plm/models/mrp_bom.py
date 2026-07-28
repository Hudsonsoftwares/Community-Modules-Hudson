# -*- coding: utf-8 -*-
from odoo import models, fields, api

class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    version = fields.Integer('Version', default=1, copy=False)
    eco_count = fields.Integer('ECO Count', compute='_compute_eco_count')
    
    def _compute_eco_count(self):
        for bom in self:
            ecos = self.env['mrp.eco'].search(['|', ('bom_id', '=', bom.id), ('new_bom_id', '=', bom.id)])
            bom.eco_count = len(ecos)

    def action_view_ecos(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'ECOs',
            'res_model': 'mrp.eco',
            'view_mode': 'list,form',
            'domain': ['|', ('bom_id', '=', self.id), ('new_bom_id', '=', self.id)],
            'context': {'default_bom_id': self.id, 'default_product_tmpl_id': self.product_tmpl_id.id},
        }
