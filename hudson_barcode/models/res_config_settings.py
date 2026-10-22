# pyrefly: ignore [missing-import]
from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    barcode_nomenclature_id = fields.Many2one(
        'barcode.nomenclature',
        related='company_id.nomenclature_id',
        readonly=False,
        string="Barcode Nomenclature"
    )
