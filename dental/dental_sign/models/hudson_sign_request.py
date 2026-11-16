# -*- coding: utf-8 -*-
from odoo import fields, models

class HudsonSignRequest(models.Model):
    _inherit = 'hudson.sign.request'

    dental_treatment_plan_id = fields.Many2one(
        'dental.treatment.plan',
        string='Treatment Plan',
        index=True,
        ondelete='set null',
    )
    dental_patient_id = fields.Many2one(
        'res.partner',
        string='Dental Patient',
        related='dental_treatment_plan_id.patient_id',
        store=True,
    )

