# pyrefly: ignore [missing-import]
from odoo import models, fields, api, _

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def action_open_picking_client_action(self):
        """ Entry point for the client action from a specific picking """
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'custom_barcode_client_action',
            'target': 'fullscreen',
            'params': {
                'model': 'stock.picking',
                'picking_id': self.id,
                'picking_type_id': self.picking_type_id.id,
            }
        }

    @api.model
    def action_open_barcode_client_action(self):
        """ Entry point for the main Barcode App """
        return {
            'type': 'ir.actions.client',
            'tag': 'custom_barcode_client_action',
            'target': 'fullscreen',
            'params': {}
        }

    def get_barcode_view_state(self):
        """ Returns the structured data representing the picking state for the frontend """
        self.ensure_one()
        
        # Load active nomenclature rules
        company = self.env.company
        nomenclature = company.nomenclature_id
        nomenclature_data = []
        if nomenclature:
            for rule in nomenclature.rule_ids:
                nomenclature_data.append({
                    'name': rule.name,
                    'type': rule.type,
                    'pattern': rule.pattern,
                    'sequence': rule.sequence,
                })

        lines = []
        for line in self.move_line_ids:
            lines.append({
                'id': line.id,
                'product_id': {
                    'id': line.product_id.id, 
                    'display_name': line.product_id.display_name, 
                    'barcode': line.product_id.barcode,
                    'tracking': line.product_id.tracking
                } if line.product_id else False,
                'qty_done': line.quantity,
                'quantity': line.quantity,
                'product_uom_qty': line.quantity_product_uom,
                'uom_id': {'id': line.product_uom_id.id, 'display_name': line.product_uom_id.name} if line.product_uom_id else False,
                'location_id': {'id': line.location_id.id, 'display_name': line.location_id.display_name, 'barcode': line.location_id.barcode} if line.location_id else False,
                'location_dest_id': {'id': line.location_dest_id.id, 'display_name': line.location_dest_id.display_name, 'barcode': line.location_dest_id.barcode} if line.location_dest_id else False,
                'lot_id': {'id': line.lot_id.id, 'name': line.lot_id.name} if line.lot_id else False,
                'lot_name': line.lot_name,
                'package_id': {'id': line.package_id.id, 'name': line.package_id.name} if line.package_id else False,
                'result_package_id': {'id': line.result_package_id.id, 'name': line.result_package_id.name} if line.result_package_id else False,
                'dummy_id': f"dummy_{line.id}"
            })
        
        return {
            'id': self.id,
            'name': self.name,
            'state': self.state,
            'quality_check_todo': getattr(self, 'quality_check_todo', False),
            'partner_id': {'id': self.partner_id.id, 'display_name': self.partner_id.display_name} if self.partner_id else False,
            'picking_type_id': {'id': self.picking_type_id.id, 'name': self.picking_type_id.name, 'code': self.picking_type_id.code},
            'location_id': {'id': self.location_id.id, 'display_name': self.location_id.display_name, 'barcode': self.location_id.barcode},
            'location_dest_id': {'id': self.location_dest_id.id, 'display_name': self.location_dest_id.display_name, 'barcode': self.location_dest_id.barcode} if self.location_dest_id else False,
            'move_line_ids': lines,
            'company_id': {'id': self.company_id.id, 'name': self.company_id.name} if self.company_id else False,
            'scheduled_date': str(self.scheduled_date) if self.scheduled_date else False,
            'origin': self.origin or False,
            'priority': self.priority or '0',
            'nomenclature': nomenclature_data,
        }

    def process_barcode_sync(self, commands):
        """
        Receives a list of dicts representing operations to perform on this picking's move lines.
        commands = [
            {'action': 'write', 'line_id': 5, 'quantity': 2},
            {'action': 'create', 'product_id': 10, 'quantity': 1, 'location_id': 1, 'location_dest_id': 2}
        ]
        """
        self.ensure_one()
        for cmd in commands:
            if cmd.get('action') == 'write':
                line = self.env['stock.move.line'].browse(cmd.get('line_id'))
                if line.exists():
                    vals = {'quantity': cmd.get('quantity')}
                    
                    lot_id = cmd.get('lot_id')
                    lot_name = cmd.get('lot_name')
                    if lot_name and not lot_id:
                        lot = self.env['stock.lot'].search([('name', '=', lot_name), ('product_id', '=', line.product_id.id)], limit=1)
                        if not lot:
                            lot = self.env['stock.lot'].create({
                                'name': lot_name,
                                'product_id': line.product_id.id,
                                'company_id': self.company_id.id,
                            })
                        vals['lot_id'] = lot.id
                    elif lot_id:
                        vals['lot_id'] = lot_id
                        
                    line.write(vals)
            elif cmd.get('action') == 'create':
                vals = {
                    'picking_id': self.id,
                    'product_id': cmd.get('product_id'),
                    'quantity': cmd.get('quantity'),
                    'location_id': cmd.get('location_id') or self.location_id.id,
                    'location_dest_id': cmd.get('location_dest_id') or self.location_dest_id.id,
                    'product_uom_id': cmd.get('product_uom_id') or False,
                }
                
                lot_id = cmd.get('lot_id')
                lot_name = cmd.get('lot_name')
                if lot_name and not lot_id:
                    lot = self.env['stock.lot'].search([('name', '=', lot_name), ('product_id', '=', vals['product_id'])], limit=1)
                    if not lot:
                        lot = self.env['stock.lot'].create({
                            'name': lot_name,
                            'product_id': vals['product_id'],
                            'company_id': self.company_id.id,
                        })
                    vals['lot_id'] = lot.id
                elif lot_id:
                    vals['lot_id'] = lot_id
                    
                if 'package_id' in cmd and cmd.get('package_id'):
                    vals['package_id'] = cmd.get('package_id')
                    
                self.env['stock.move.line'].create(vals)
        
        return True

    def action_barcode_autofill(self):
        """ Automatically fill quantities to bypass immediate transfer """
        self.ensure_one()
        has_qty = any(line.quantity > 0 for line in self.move_line_ids)
        if not has_qty:
            for line in self.move_line_ids:
                line.quantity = line.reserved_uom_qty or line.quantity_product_uom or 0.0
        return True

    def action_barcode_create_return(self):
        self.ensure_one()
        # 1. Initialize the wizard with defaults for this picking
        ctx = dict(self.env.context, active_ids=[self.id], active_id=self.id, active_model='stock.picking')
        default_vals = self.env['stock.return.picking'].with_context(ctx).default_get(
            ['product_return_moves', 'picking_id', 'location_id', 'company_id']
        )
        
        # Ensure picking_id is set
        default_vals['picking_id'] = self.id
        
        # 2. Create the wizard record
        wizard = self.env['stock.return.picking'].with_context(ctx).create(default_vals)
        
        # 3. Use action_create_returns_all to automatically fill the quantities
        #    with the total returnable amount (since Odoo defaults them to 0),
        #    and then create the return picking.
        action = wizard.action_create_returns_all()
        
        # 4. The wizard creates the return picking and returns an action dict.
        return action.get('res_id')

