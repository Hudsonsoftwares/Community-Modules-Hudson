# pyrefly: ignore [missing-import]
from odoo import models, api, _

class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    @api.model
    def barcode_get_allowed_uoms(self, product_id):
        """ Units the Barcode app may offer for a product: exactly the move line's own
        `allowed_uom_ids` (Odoo 20: product units + packagings + vendor units), computed
        on an unsaved line so nothing is written. """
        if not product_id:
            return []
        line = self.new({'product_id': product_id})
        # _origin: values computed on a new record are new-record ids; return the real records
        return [{'id': uom.id, 'name': uom.display_name} for uom in line.allowed_uom_ids._origin]
