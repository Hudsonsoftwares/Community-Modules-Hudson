# -*- coding: utf-8 -*-
from odoo import fields, models

class HudsonSignTemplate(models.Model):
    _inherit = 'hudson.sign.template'

    treatment_id = fields.Many2one(
        'product.template',
        string='Dental Treatment',
        domain=[('is_dental_treatment', '=', True)],
        help='Dental treatment associated with this informed consent form.',
    )

