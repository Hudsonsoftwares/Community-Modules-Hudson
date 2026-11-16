# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError


class DentalCase(models.Model):
    _inherit = 'dental.case'

    # Inverse of the referral; also used by the specialist ir.access rows to open the referred case's records
    second_opinion_ids = fields.One2many('dental.second.opinion', 'case_id', string='Second Opinions')
    second_opinion_count = fields.Integer(string='Second Opinion Count', compute='_compute_second_opinion_count')

    def _compute_second_opinion_count(self):
        counts = dict(self.env['dental.second.opinion']._read_group(
            [('case_id', 'in', self.ids)], ['case_id'], ['__count']))
        for case in self:
            case.second_opinion_count = counts.get(case, 0)

    def action_view_second_opinions(self):
        self.ensure_one()
        return {
            'name': _('Second Opinions for %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.second.opinion',
            'view_mode': 'list,form',
            'domain': [('case_id', '=', self.id)],
            'context': {'default_case_id': self.id},
        }

    def action_request_second_opinion(self):
        self.ensure_one()
        if self.state == 'cancelled':
            raise UserError(_("A second opinion cannot be requested on a cancelled case."))
        return {
            'name': _('Request Second Opinion'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.second.opinion',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_case_id': self.id,
                'default_clinical_summary': self.chief_complaint or False,
                'default_examination_ids': self.examination_ids.ids,
                'default_diagnosis_ids': self.diagnosis_ids.ids,
                'default_treatment_plan_id': self.treatment_plan_ids[:1].id,
            },
        }
