# -*- coding: utf-8 -*-
from odoo import api, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        if result and config and config.dental_pharmacy_counter:
            result += [f for f in ('is_dental_patient', 'dental_patient_id', 'allergy_status') if f in self._fields]
        return result
