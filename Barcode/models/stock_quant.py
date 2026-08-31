# pyrefly: ignore [missing-import]
from odoo import models, api

class StockQuant(models.Model):
    _inherit = 'stock.quant'

    @api.model
    def action_open_inventory_client_action(self):
        """ Entry point for inventory adjustments from Barcode app """
        return {
            'type': 'ir.actions.client',
            'tag': 'custom_barcode_client_action',
            'target': 'fullscreen',
            'params': {
                'model': 'stock.quant',
            }
        }

    @api.model
    def get_barcode_inventory_state(self, domain=None):
        """ Returns the structured data representing active quants for the frontend physical inventory """
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
        
        # Get quants
        search_domain = domain if domain else [('location_id.usage', '=', 'internal'), ('inventory_quantity_set', '=', True)]
        quants = self.search(search_domain, limit=100) # Limit to 100 for now to prevent massive payloads
        lines = []
        for quant in quants:
            lines.append({
                'id': quant.id,
                'product_id': {
                    'id': quant.product_id.id,
                    'display_name': quant.product_id.display_name,
                    'barcode': quant.product_id.barcode,
                    'tracking': quant.product_id.tracking
                } if quant.product_id else False,
                'quantity': quant.inventory_quantity if quant.inventory_quantity_set else quant.quantity,
                'product_uom_qty': quant.quantity, # On hand quantity
                'uom_id': {'id': quant.product_uom_id.id, 'display_name': quant.product_uom_id.name} if quant.product_uom_id else False,
                'location_id': {'id': quant.location_id.id, 'display_name': quant.location_id.display_name, 'barcode': quant.location_id.barcode} if quant.location_id else False,
                'location_dest_id': False, # N/A for quants
                'lot_id': {'id': quant.lot_id.id, 'name': quant.lot_id.name} if quant.lot_id else False,
                'package_id': {'id': quant.package_id.id, 'name': quant.package_id.name} if quant.package_id else False,
                'dummy_id': f"quant_{quant.id}",
                'inventory_quantity_set': quant.inventory_quantity_set,
            })
            
        default_location = self.env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1).lot_stock_id
        
        return {
            'name': 'Physical Inventory',
            'move_line_ids': lines,
            'nomenclature': nomenclature_data,
            'default_location_id': [default_location.id, default_location.display_name] if default_location else False
        }

    @api.model
    def process_barcode_inventory_sync(self, commands, apply_now=True):
        """
        Receives a list of dicts representing operations to perform on quants.
        commands = [
            {'action': 'write', 'quant_id': 5, 'inventory_quantity': 2},
            {'action': 'create', 'product_id': 10, 'inventory_quantity': 1, 'location_id': 1}
        ]
        """
        quants_to_apply = self.env['stock.quant']
        for cmd in commands:
            if cmd.get('action') == 'write':
                quant = self.browse(cmd.get('quant_id'))
                if quant.exists():
                    quant.action_set_inventory_quantity()
                    vals = {'inventory_quantity': cmd.get('inventory_quantity')}
                    
                    lot_id = cmd.get('lot_id')
                    lot_name = cmd.get('lot_name')
                    if lot_name and not lot_id:
                        lot = self.env['stock.lot'].search([('name', '=', lot_name), ('product_id', '=', quant.product_id.id)], limit=1)
                        if not lot:
                            lot = self.env['stock.lot'].create({
                                'name': lot_name,
                                'product_id': quant.product_id.id,
                                'company_id': self.env.company.id,
                            })
                        vals['lot_id'] = lot.id
                    elif lot_id:
                        vals['lot_id'] = lot_id
                        
                    quant.write(vals)
                    quants_to_apply |= quant
            elif cmd.get('action') == 'create':
                # Check if quant already exists for product/location/lot/package
                domain = [
                    ('product_id', '=', cmd.get('product_id')),
                    ('location_id', '=', cmd.get('location_id'))
                ]
                if 'lot_id' in cmd:
                    domain.append(('lot_id', '=', cmd.get('lot_id') or False))
                if 'package_id' in cmd:
                    domain.append(('package_id', '=', cmd.get('package_id') or False))
                    
                existing_quant = self.search(domain, limit=1)
                if existing_quant:
                    existing_quant.action_set_inventory_quantity()
                    existing_quant.write({'inventory_quantity': cmd.get('inventory_quantity')})
                    quants_to_apply |= existing_quant
                else:
                    vals = {
                        'product_id': cmd.get('product_id'),
                        'location_id': cmd.get('location_id'),
                        'inventory_quantity': cmd.get('inventory_quantity'),
                    }
                    
                    lot_id = cmd.get('lot_id')
                    lot_name = cmd.get('lot_name')
                    if lot_name and not lot_id:
                        lot = self.env['stock.lot'].search([('name', '=', lot_name), ('product_id', '=', vals['product_id'])], limit=1)
                        if not lot:
                            lot = self.env['stock.lot'].create({
                                'name': lot_name,
                                'product_id': vals['product_id'],
                                'company_id': self.env.company.id,
                            })
                        vals['lot_id'] = lot.id
                    elif lot_id:
                        vals['lot_id'] = lot_id
                        
                    if 'package_id' in cmd and cmd.get('package_id'):
                        vals['package_id'] = cmd.get('package_id')
                        
                    quant = self.create(vals)
                    quant.action_set_inventory_quantity()
                    quants_to_apply |= quant
                    
        # Apply the inventory adjustments
        if quants_to_apply and apply_now:
            quants_to_apply.action_apply_inventory()
            
        return True
