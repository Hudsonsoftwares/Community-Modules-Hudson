# pyrefly: ignore [missing-import]
from odoo import models, api, _

class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'


