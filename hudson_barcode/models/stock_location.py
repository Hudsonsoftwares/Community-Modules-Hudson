# -*- coding: utf-8 -*-
# pyrefly: ignore [missing-import]
from odoo import models, fields, api

class StockLocation(models.Model):
    _inherit = 'stock.location'

    barcode_html = fields.Html(
        string='Barcode Image',
        compute='_compute_barcode_html',
        store=False,
        readonly=True,
    )

    @api.depends('barcode')
    def _compute_barcode_html(self):
        for loc in self:
            if loc.barcode:
                loc.barcode_html = f'<img src="/report/barcode/Code128/{loc.barcode}?width=250&height=50" style="width: 100%; max-width: 250px; height: auto;" alt="Barcode"/>'
            else:
                loc.barcode_html = False
