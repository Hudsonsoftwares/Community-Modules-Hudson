# -*- coding: utf-8 -*-
from odoo import fields, models

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    consent_template_id = fields.Many2one(
        'hudson.sign.template',
        string='Consent Template',
        help='Dedicated signature template used when this treatment is included in a treatment plan.',
    )

