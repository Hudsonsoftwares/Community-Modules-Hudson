# pyrefly: ignore [missing-import]
from odoo import http, _
# pyrefly: ignore [missing-import]
from odoo.http import request

class BarcodeController(http.Controller):

    @http.route('/custom_barcode/scan', type='json', auth='user')
    def process_barcode(self, barcode, model='stock.picking', record_id=False, **kw):
        """
        Deprecated. Barcode parsing is now handled entirely on the JS frontend 
        using BarcodeParser to reduce RPC overhead.
        """
        return {'error': _('Server-side barcode parsing is deprecated. Update your frontend.')}
