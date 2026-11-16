# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    dental_has_pharmacy = fields.Boolean(
        string='In-house Pharmacy',
        default=True,
        help='When enabled, confirmed prescriptions of this clinic branch go to the in-house pharmacy '
             'for dispensing and billing. When disabled, the prescription is issued to the patient '
             '(printed / emailed) to buy outside, and the front desk bills only the visit.',
    )


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    dental_has_pharmacy = fields.Boolean(related='company_id.dental_has_pharmacy', readonly=False)
