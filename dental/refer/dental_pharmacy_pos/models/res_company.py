# -*- coding: utf-8 -*-
from odoo import fields, models

DISPENSE_MODES = [
    ('backend', 'Pharmacy App (dispense form)'),
    ('pos', 'Point of Sale Counter'),
]


class ResCompany(models.Model):
    _inherit = 'res.company'

    dental_dispense_mode = fields.Selection(
        DISPENSE_MODES, string='Dispensing Mode', default='backend', required=True,
        help='Pharmacy App: the pharmacist dispenses and invoices from the prescription (dispense form).\n'
             'Point of Sale Counter: prescriptions are dispensed, paid and invoiced at a POS pharmacy counter; '
             'the dispense record is created automatically from the paid POS order.')

    def _dental_dispenses_at_pos(self):
        self.ensure_one()
        return self.dental_has_pharmacy and self.dental_dispense_mode == 'pos'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    dental_dispense_mode = fields.Selection(related='company_id.dental_dispense_mode', readonly=False)
