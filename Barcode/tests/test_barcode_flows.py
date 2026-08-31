# pyrefly: ignore [missing-import]
from odoo.tests import tagged, HttpCase

@tagged('post_install', '-at_install')
class TestBarcodeFlows(HttpCase):

    def test_01_barcode_picking_sync(self):
        """
        Server-side unit test to verify that process_barcode_sync
        correctly handles the create action with lot_id.
        """
        product = self.env['product.product'].create({
            'name': 'Test Product Barcode',
            'is_storable': True,
            'tracking': 'lot',
            'barcode': '1234567890128'
        })
        
        lot = self.env['stock.lot'].create({
            'name': 'LOT001',
            'product_id': product.id,
            'company_id': self.env.company.id,
        })
        
        picking_type = self.env['stock.picking.type'].search([], limit=1)
        location = self.env['stock.location'].search([('usage', '=', 'internal')], limit=1)
        dest_location = self.env['stock.location'].search([('usage', '=', 'customer')], limit=1)
        
        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'location_id': location.id,
            'location_dest_id': dest_location.id,
        })
        
        commands = [{
            'action': 'create',
            'product_id': product.id,
            'quantity': 5,
            'location_id': location.id,
            'location_dest_id': dest_location.id,
            'lot_id': lot.id,
        }]
        
        picking.process_barcode_sync(commands)
        
        self.assertEqual(len(picking.move_line_ids), 1)
        self.assertEqual(picking.move_line_ids.quantity, 5)
        self.assertEqual(picking.move_line_ids.lot_id.id, lot.id)
        
        # In a real tour, we would do:
        # self.start_tour("/web", 'test_barcode_app_tour', login="admin")
