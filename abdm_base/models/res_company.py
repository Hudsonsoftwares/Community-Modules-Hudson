from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # One ABDM client (bridge) can serve many facilities: each company is a
    # facility registered in the Health Facility Registry (HFR).
    abdm_hip_id = fields.Char(
        string='ABDM Facility ID (HFR)',
        help='Health Facility Registry ID of this clinic, used as HIP / HIU ID '
             'in ABDM requests (e.g. IN2710000123).',
        copy=False,
    )
    abdm_hip_name = fields.Char(
        string='ABDM Facility Name',
        help='Facility name exactly as registered in HFR.',
        copy=False,
    )
