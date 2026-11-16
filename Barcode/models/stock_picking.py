# pyrefly: ignore [missing-import]
from odoo import models, fields, api, _
# pyrefly: ignore [missing-import]
from odoo.exceptions import UserError

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

    def action_client_action(self):
        """'Barcode' smart button of the transfer form: open this transfer in the Barcode app."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'custom_barcode_client_action',
            'name': self.name,
            'target': 'fullscreen',
            'params': {'picking_id': self.id},
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

        grouped_lines = {}
        for line in self.move_line_ids:
            # A line of an open move holding 0 units (e.g. reset to 0 because nothing was scanned
            # on it) carries nothing: its demand is shown by the move's remaining-demand line.
            if line.uom_id.is_zero(line.quantity) and line.move_id and line.move_id.state not in ('done', 'cancel'):
                continue
            tracking = line.product_id.tracking if line.product_id else 'none'
            key = (
                line.product_id.id if line.product_id else False,
                line.location_id.id if line.location_id else False,
                line.location_dest_id.id if line.location_dest_id else False,
                line.lot_id.id if line.lot_id else False,
                line.package_id.id if line.package_id else False,
                line.result_package_id.id if line.result_package_id else False,
                line.result_package_id.parent_package_id.id if (line.result_package_id and line.result_package_id.parent_package_id) else False,
            )
            
            # Do not group serial tracked products unless they don't have a lot assigned yet?
            # Actually, standard Odoo doesn't group serial tracked items.
            if tracking == 'serial':
                key = ('serial', line.id)
                
            if key not in grouped_lines:
                grouped_lines[key] = {
                    'id': line.id,
                    'move_id': line.move_id.id if line.move_id else False,
                    'product_id': {
                        'id': line.product_id.id, 
                        'display_name': line.product_id.display_name, 
                        'barcode': line.product_id.barcode,
                        'tracking': tracking
                    } if line.product_id else False,
                    'qty_done': line.quantity,
                    'quantity': line.quantity,
                    'product_uom_qty': line.quantity_product_uom,
                    'picked': line.picked,
                    'uom_id': {'id': line.uom_id.id, 'display_name': line.uom_id.name} if line.uom_id else False,
                    'location_id': {'id': line.location_id.id, 'display_name': line.location_id.display_name, 'barcode': line.location_id.barcode} if line.location_id else False,
                    'location_dest_id': {'id': line.location_dest_id.id, 'display_name': line.location_dest_id.display_name, 'barcode': line.location_dest_id.barcode} if line.location_dest_id else False,
                    'lot_id': {'id': line.lot_id.id, 'name': line.lot_id.name} if line.lot_id else False,
                    'lot_name': line.lot_name,
                    # 'path': full package chain, as Odoo 20 shows it (source: complete_name, destination: dest_complete_name)
                    'package_id': {'id': line.package_id.id, 'name': line.package_id.name, 'path': line.package_id.complete_name} if line.package_id else False,
                    'result_package_id': {'id': line.result_package_id.id, 'name': line.result_package_id.name, 'path': line.result_package_id.dest_complete_name} if line.result_package_id else False,
                    'destination_container_package': {'id': line.result_package_id.parent_package_id.id, 'name': line.result_package_id.parent_package_id.name} if line.result_package_id and line.result_package_id.parent_package_id else False,
                    'dummy_id': f"dummy_{line.id}"
                }
            else:
                grouped_lines[key]['qty_done'] += line.quantity
                grouped_lines[key]['quantity'] += line.quantity
                grouped_lines[key]['product_uom_qty'] += line.quantity_product_uom
                grouped_lines[key]['picked'] = grouped_lines[key]['picked'] or line.picked
                
        for move in self.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
            if move.move_line_ids:
                # Demand not covered by the move's lines yet (e.g. after packing part of it):
                # show it as its own line so the remaining quantity stays visible and scannable.
                remaining = move.product_uom_qty - move.quantity
                if move.uom_id.compare(remaining, 0) > 0:
                    grouped_lines[('remaining', move.id)] = {
                        'id': f'virtual_{move.id}',
                        'move_id': move.id,
                        'product_id': {
                            'id': move.product_id.id,
                            'display_name': move.product_id.display_name,
                            'barcode': move.product_id.barcode,
                            'tracking': move.product_id.tracking,
                        } if move.product_id else False,
                        'qty_done': 0.0,
                        'quantity': 0.0,
                        'product_uom_qty': remaining,
                        'picked': False,
                        'uom_id': {'id': move.uom_id.id, 'display_name': move.uom_id.name} if move.uom_id else False,
                        'location_id': {'id': move.location_id.id, 'display_name': move.location_id.display_name, 'barcode': move.location_id.barcode} if move.location_id else False,
                        'location_dest_id': {'id': move.location_dest_id.id, 'display_name': move.location_dest_id.display_name, 'barcode': move.location_dest_id.barcode} if move.location_dest_id else False,
                        'lot_id': False,
                        'lot_name': False,
                        'package_id': False,
                        'result_package_id': False,
                        'destination_container_package': False,
                        'dummy_id': f"virtual_{move.id}"
                    }
            if not move.move_line_ids:
                key = (
                    move.product_id.id if move.product_id else False,
                    move.location_id.id if move.location_id else False,
                    move.location_dest_id.id if move.location_dest_id else False,
                    False,
                    False,
                    False,
                    False,
                )
                if key not in grouped_lines:
                    grouped_lines[key] = {
                        'id': f'virtual_{move.id}',
                        'move_id': move.id,
                        'product_id': {
                            'id': move.product_id.id,
                            'display_name': move.product_id.display_name,
                            'barcode': move.product_id.barcode,
                            'tracking': move.product_id.tracking,
                        } if move.product_id else False,
                        'qty_done': 0.0,
                        'quantity': 0.0,
                        'product_uom_qty': move.product_uom_qty,
                        'picked': False,
                        'uom_id': {'id': move.uom_id.id, 'display_name': move.uom_id.name} if move.uom_id else False,
                        'location_id': {'id': move.location_id.id, 'display_name': move.location_id.display_name, 'barcode': move.location_id.barcode} if move.location_id else False,
                        'location_dest_id': {'id': move.location_dest_id.id, 'display_name': move.location_dest_id.display_name, 'barcode': move.location_dest_id.barcode} if move.location_dest_id else False,
                        'lot_id': False,
                        'lot_name': False,
                        'package_id': False,
                        'result_package_id': False,
                        'destination_container_package': False,
                        'dummy_id': f"virtual_{move.id}"
                    }

        lines = list(grouped_lines.values())
        
        return {
            'id': self.id,
            'name': self.name,
            'state': self.state,
            'quality_check_todo': getattr(self, 'quality_check_todo', False),
            # Odoo 20: the "Reception Report" group (stock.group_reception_report) no longer
            # exists; the feature is enabled per operation type (auto_show_allocation_report),
            # which is already part of `show_allocation`.
            'show_allocation': getattr(self, 'show_allocation', False),
            'partner_id': {'id': self.partner_id.id, 'display_name': self.partner_id.display_name} if self.partner_id else False,
            'picking_type_id': {'id': self.picking_type_id.id, 'name': self.picking_type_id.name, 'code': self.picking_type_id.code},
            'location_id': {'id': self.location_id.id, 'display_name': self.location_id.display_name, 'barcode': self.location_id.barcode},
            'location_dest_id': {'id': self.location_dest_id.id, 'display_name': self.location_dest_id.display_name, 'barcode': self.location_dest_id.barcode} if self.location_dest_id else False,
            'move_line_ids': lines,
            'backorders': [{'id': b.id, 'name': b.name} for b in getattr(self, 'backorder_ids', [])],
            'company_id': {'id': self.company_id.id, 'name': self.company_id.name} if self.company_id else False,
            'scheduled_date': str(self.scheduled_date) if self.scheduled_date else False,
            'origin': self.origin or False,
            'priority': self.priority or '0',
            'nomenclature': nomenclature_data,
        }

    def _resolve_package_id(self, package_val):
        if not package_val:
            return False
        if isinstance(package_val, int):
            return package_val
        if isinstance(package_val, dict):
            pkg_id = package_val.get('id')
            pkg_name = package_val.get('name') or package_val.get('display_name')
            if pkg_id:
                return pkg_id
            if pkg_name:
                pkg = self.env['stock.package'].search([('name', '=', pkg_name)], limit=1)
                if not pkg:
                    pkg = self.env['stock.package'].create({'name': pkg_name})
                return pkg.id
        elif isinstance(package_val, list) and len(package_val) > 1:
            if package_val[0]:
                return package_val[0]
            if package_val[1]:
                pkg = self.env['stock.package'].search([('name', '=', package_val[1])], limit=1)
                if not pkg:
                    pkg = self.env['stock.package'].create({'name': package_val[1]})
                return pkg.id
        elif isinstance(package_val, str):
            pkg = self.env['stock.package'].search([('name', '=', package_val)], limit=1)
            if not pkg:
                pkg = self.env['stock.package'].create({'name': package_val})
            return pkg.id
        return False

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
                    if cmd.get('product_uom_id'):
                        vals['uom_id'] = cmd.get('product_uom_id')
                    
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
                        
                    if 'package_id' in cmd:
                        pkg_id = self._resolve_package_id(cmd.get('package_id'))
                        if pkg_id: vals['package_id'] = pkg_id
                    
                    if 'result_package_id' in cmd:
                        res_pkg_id = self._resolve_package_id(cmd.get('result_package_id'))
                        if res_pkg_id: vals['result_package_id'] = res_pkg_id
                        
                    line.write(vals)
                    
                    if 'destination_container_package' in cmd and line.result_package_id:
                        container_pkg_id = self._resolve_package_id(cmd.get('destination_container_package'))
                        if container_pkg_id:
                            line.result_package_id.parent_package_id = container_pkg_id
            elif cmd.get('action') == 'create':
                if not cmd.get('quantity'):
                    # nothing scanned on this (virtual) line: no move line to create
                    continue
                vals = {
                    'picking_id': self.id,
                    'product_id': cmd.get('product_id'),
                    'quantity': cmd.get('quantity'),
                    'location_id': cmd.get('location_id') or self.location_id.id,
                    'location_dest_id': cmd.get('location_dest_id') or self.location_dest_id.id,
                }
                # Odoo 20: `uom_id` (was `product_uom_id`) is required and computed from
                # the product; only pass it when the client sent one, otherwise let it compute.
                if cmd.get('product_uom_id'):
                    vals['uom_id'] = cmd.get('product_uom_id')

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
                    
                if 'package_id' in cmd:
                    pkg_id = self._resolve_package_id(cmd.get('package_id'))
                    if pkg_id: vals['package_id'] = pkg_id
                    
                if 'result_package_id' in cmd:
                    res_pkg_id = self._resolve_package_id(cmd.get('result_package_id'))
                    if res_pkg_id: vals['result_package_id'] = res_pkg_id
                    
                new_line = self.env['stock.move.line'].create(vals)
                
                if 'destination_container_package' in cmd and new_line.result_package_id:
                    container_pkg_id = self._resolve_package_id(cmd.get('destination_container_package'))
                    if container_pkg_id:
                        new_line.result_package_id.parent_package_id = container_pkg_id
        
        return True

    def action_barcode_autofill(self):
        """ Automatically fill quantities to bypass immediate transfer """
        self.ensure_one()
        has_qty = any(line.quantity > 0 for line in self.move_line_ids)
        if not has_qty:
            for line in self.move_line_ids:
                line.quantity = line.reserved_uom_qty or line.quantity_product_uom or 0.0
        return True

    def barcode_confirm_backorder(self):
        """
        Called from the Barcode App when the user clicks 'Create Backorder'.
        Validates the transfer for the qty that was actually processed, and lets Odoo
        auto-create a backorder for whatever remains.
        """
        self.ensure_one()
        # Validate with skip_backorder so we don't loop back into the wizard,
        # but WITHOUT cancel_backorder so the remaining qty creates a backorder.
        self.with_context(skip_backorder=True).button_validate()
        # Invalidate cache so backorder_ids is re-read from DB
        self.invalidate_recordset(['backorder_ids', 'state'])
        new_backorder = self.backorder_ids.sorted('id', reverse=True)[:1]
        return {
            'success': True,
            'backorder': {
                'id': new_backorder.id,
                'name': new_backorder.name,
            } if new_backorder else False,
        }

    def barcode_cancel_backorder(self):
        """
        Called from the Barcode App when the user clicks 'No Backorder'.
        Validates the transfer for the qty processed and CANCELS the remaining demand.
        """
        self.ensure_one()
        self.with_context(
            skip_backorder=True,
            picking_ids_not_to_backorder=self.ids,
        ).button_validate()
        return {'success': True}

    def action_barcode_create_return(self):
        self.ensure_one()
        # Odoo 20 removed the `stock.return.picking` wizard: returns are created
        # directly on the picking. Reproduce what the old wizard's
        # `action_create_returns_all` did:
        # 1. Create the (draft) return picking.
        new_picking = self._create_return()
        # 2. Set every return move's demand to the full returnable quantity.
        new_picking.action_return_all()
        # 3. Only keep the lines that actually have something to return, and
        #    refuse to create an empty return (same error as the old wizard).
        empty_moves = new_picking.move_ids.filtered(lambda m: m.uom_id.is_zero(m.product_uom_qty))
        if empty_moves == new_picking.move_ids:
            new_picking.unlink()
            raise UserError(_("Please specify at least one non-zero quantity."))
        empty_moves.unlink()
        # 4. Confirm and reserve it so it is ready to be scanned.
        new_picking.action_confirm()
        new_picking.action_assign()
        return new_picking.id

class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    is_barcode_picking_type = fields.Boolean(
        string="Is Barcode Picking Type", 
        default=True,
        help="Custom field to indicate if this type is used in barcode operations."
    )

    count_mo_confirmed = fields.Integer(
        string="Count Mo Confirmed",
        compute='_compute_count_mo_confirmed',
        help="Custom field to count confirmed MOs for Excel export parity."
    )

    def _compute_count_mo_confirmed(self):
        # We dynamically check if 'mrp.production' exists in the environment to avoid crashes
        if 'mrp.production' in self.env:
            for record in self:
                record.count_mo_confirmed = self.env['mrp.production'].search_count([
                    ('picking_type_id', '=', record.id),
                    ('state', '=', 'confirmed')
                ])
        else:
            for record in self:
                record.count_mo_confirmed = 0

    @api.model
    def _get_barcode_demo_sheet_sections(self):
        """ Data for the "Barcode Demo Data Sheet" report (Odoo Online-style layout).

        Built from the current company's own records, and only with barcodes this
        app can act on. Sections whose data or feature is missing are left out.
        Returns [{'title', 'hint', 'rows': [[{'label', 'code'}, ...], ...]}, ...]
        """
        company = self.env.company
        user = self.env.user
        Product = self.env['product.product']
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
        validate = {'label': _('Validate'), 'code': 'O-CMD.VALIDATE'}
        put_in_pack = {'label': _('Put in Pack'), 'code': 'O-CMD.PUT-IN-PACK'}

        def item(record, code):
            return {'label': record.display_name, 'code': code}

        def products(tracking, limit):
            return Product.search([
                ('barcode', '!=', False), ('is_storable', '=', True), ('tracking', '=', tracking),
                ('company_id', 'in', [False, company.id]),
            ], limit=limit)

        receipt_type = warehouse.in_type_id if warehouse.in_type_id.barcode else self.browse()
        # Odoo 20: untracked products have tracking = False (the 'none' value was removed)
        plain_products = products(False, 2)
        has_packages = user.has_group('stock.group_tracking_lot')
        sections = []

        # 1. Receive products in stock (+ process an existing ready delivery)
        rows = []
        if receipt_type and plain_products:
            rows.append([item(receipt_type, receipt_type.barcode),
                         item(plain_products[0], plain_products[0].barcode), validate])
        delivery_line = self.env['stock.move'].search([
            ('picking_id.picking_type_code', '=', 'outgoing'), ('picking_id.state', '=', 'assigned'),
            ('picking_id.company_id', '=', company.id), ('product_id.barcode', '!=', False),
        ], limit=1)
        if delivery_line:
            rows.append([item(delivery_line.picking_id, delivery_line.picking_id.name),
                         item(delivery_line.product_id, delivery_line.product_id.barcode), validate])
        if rows:
            sections.append({
                'title': _('Receive products in stock'),
                'hint': _('Scan the operation type and press "New" (or scan an existing transfer), then scan the products and Validate.'),
                'rows': rows,
            })

        # 2. Receive products tracked by lot number
        lot_product = products('lot', 1)
        if receipt_type and lot_product and user.has_group('stock.group_production_lot'):
            lots = self.env['stock.lot'].search([('product_id', '=', lot_product.id)], limit=2)
            sections.append({
                'title': _('Receive products tracked by lot number'),
                'hint': _('Scan the product, then its lot number.'),
                'rows': [[item(receipt_type, receipt_type.barcode), item(lot_product, lot_product.barcode)]
                         + [item(lot, lot.name) for lot in lots] + [validate]],
            })

        # 3. Internal transfer: scanning a location sets the source location
        internal_type = warehouse.int_type_id
        stock_location = warehouse.lot_stock_id
        if (internal_type.barcode and stock_location.barcode and plain_products
                and user.has_group('stock.group_stock_multi_locations')):
            sections.append({
                'title': _('Internal transfer'),
                'hint': _('Scanning a location sets the source location of the next scanned products.'),
                'rows': [[item(internal_type, internal_type.barcode), item(stock_location, stock_location.barcode),
                          item(plain_products[-1], plain_products[-1].barcode), validate]],
            })

        # 4. Put in Pack
        if receipt_type and plain_products and has_packages:
            sections.append({
                'title': _('Put in Pack'),
                'hint': False,
                'rows': [[item(receipt_type, receipt_type.barcode),
                          item(plain_products[0], plain_products[0].barcode), put_in_pack, validate]],
            })

        # 5. Receive products inside packages (an existing ready receipt with a package)
        if has_packages:
            package_line = self.env['stock.move.line'].search([
                ('picking_id.picking_type_code', '=', 'incoming'), ('picking_id.state', '=', 'assigned'),
                ('picking_id.company_id', '=', company.id),
                '|', ('result_package_id', '!=', False), ('package_id', '!=', False),
            ], limit=1)
            if package_line:
                package = package_line.result_package_id or package_line.package_id
                sections.append({
                    'title': _('Receive products inside packages'),
                    'hint': _('Scan the transfer, then the package to receive all its content.'),
                    'rows': [[item(package_line.picking_id, package_line.picking_id.name),
                              item(package, package.name), validate]],
                })
        return sections

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def action_put_in_pack(self):
        """Barcode 'Put in Pack' on a manufacturing order (Odoo Online): puts the finished
        product in a new package even before anything is produced (0 / 10), so the goods are
        produced into it; the MO's 'Packages' smart button then shows it. Uses Odoo's own
        packing steps (package type wizard / label printing when configured)."""
        self.ensure_one()
        if self.state in ('done', 'cancel'):
            return False
        lines = (self.move_finished_ids - self.move_byproduct_ids).move_line_ids.filtered(
            lambda ml: ml.state not in ('done', 'cancel') and not ml.result_package_id)
        if not lines:
            return False
        if any(not ml.uom_id.is_zero(ml.quantity) for ml in lines):
            # something produced: Odoo's standard put in pack
            return lines.action_put_in_pack()
        # nothing produced yet (Odoo's generic packing skips 0-quantity lines): pack the line itself
        action = lines._pre_put_in_pack_hook(lines)
        if action:
            return action
        package = lines._put_in_pack()
        return lines._post_put_in_pack_hook(package)

    def barcode_mark_done(self):
        """Barcode 'Produce'. Same as the MO's Produce button, but keeps the package of the
        finished product (Put in Pack): when nothing was entered as produced, Odoo produces
        the full quantity itself and rebuilds the finished line, which loses its package."""
        self.ensure_one()
        finished = self.move_finished_ids.filtered(
            lambda m: m.product_id == self.product_id and m.state not in ('done', 'cancel'))
        package = finished.move_line_ids.result_package_id[:1]
        if package and self.uom_id.is_zero(self.qty_producing) and self._auto_production_checks():
            # do Odoo's automatic 'produce all' now, then put the produced goods back in the package
            self._set_quantities()
            finished.move_line_ids.filtered(lambda ml: not ml.result_package_id).result_package_id = package
        return self.button_mark_done()

    @api.model
    def barcode_get_new_production_state(self, picking_type_id=False):
        """'New' MO screen of the Barcode app (nothing created yet): barcode rules, and where
        the produced goods will go (the operation type's destination, like the MO form)."""
        nomenclature = self.env.company.nomenclature_id
        picking_type = self.env['stock.picking.type'].browse(int(picking_type_id)).exists() if picking_type_id else False
        dest = picking_type.default_location_dest_id if picking_type else False
        return {
            'location_dest_id': [dest.id, dest.display_name] if dest else False,
            'nomenclature': [{
                'name': rule.name, 'type': rule.type, 'pattern': rule.pattern, 'sequence': rule.sequence,
            } for rule in nomenclature.rule_ids] if nomenclature else [],
        }

    @api.model
    def barcode_create_production(self, picking_type_id, product_id, product_qty=1.0):
        """'New' MO in the Barcode app: the first scanned product is the product to produce.
        Creates the MO for it (with its bill of materials, like the MO form) and confirms it
        so its components can be scanned. Returns the new MO id."""
        picking_type = self.env['stock.picking.type'].browse(int(picking_type_id)).exists()
        if not picking_type or picking_type.code != 'mrp_operation':
            raise UserError(_("This operation type cannot create manufacturing orders."))
        product = self.env['product.product'].browse(int(product_id)).exists()
        if not product:
            raise UserError(_("Product not found."))
        if product.type != 'consu':
            raise UserError(_("%s cannot be manufactured: only goods can be produced.", product.display_name))
        company = picking_type.company_id or self.env.company
        bom = self.env['mrp.bom']._bom_find(
            product, picking_type=picking_type, company_id=company.id, bom_type='normal')[product]
        vals = {
            'product_id': product.id,
            'product_qty': product_qty if product_qty and product_qty > 0 else 1.0,
            'picking_type_id': picking_type.id,
            'company_id': company.id,
        }
        if bom:
            vals['bom_id'] = bom.id
        production = self.with_company(company).create(vals)
        production.action_confirm()
        return production.id

    def get_barcode_view_state(self):
        """ Returns the structured data representing the MO state for the frontend """
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
        
        # Helper to format lines
        def format_line(line, qty, max_qty, is_finished=False, is_byproduct=False):
            return {
                'id': line.id,
                'move_id': line.move_id.id if line.move_id else False,
                'product_id': {
                    'id': line.product_id.id, 
                    'display_name': line.product_id.display_name, 
                    'barcode': line.product_id.barcode,
                    'tracking': line.product_id.tracking
                } if line.product_id else False,
                'qty_done': qty,
                'quantity': qty,
                'product_uom_qty': max_qty,
                'picked': line.picked,
                'is_finished_product': is_finished,
                'is_byproduct': is_byproduct,
                'uom_id': {'id': line.uom_id.id, 'display_name': line.uom_id.name} if line.uom_id else False,
                'location_id': {'id': line.location_id.id, 'display_name': line.location_id.display_name, 'barcode': line.location_id.barcode} if line.location_id else False,
                'location_dest_id': {'id': line.location_dest_id.id, 'display_name': line.location_dest_id.display_name, 'barcode': line.location_dest_id.barcode} if line.location_dest_id else False,
                'lot_id': {'id': line.lot_id.id, 'name': line.lot_id.name} if line.lot_id else False,
                'lot_name': line.lot_name,
                'package_id': {'id': line.package_id.id, 'name': line.package_id.name} if line.package_id else False,
                'result_package_id': {'id': line.result_package_id.id, 'name': line.result_package_id.name} if line.result_package_id else False,
                'destination_container_package': {'id': line.result_package_id.parent_package_id.id, 'name': line.result_package_id.parent_package_id.name} if line.result_package_id and line.result_package_id.parent_package_id else False,
                'owner_id': {'id': line.owner_id.id, 'display_name': line.owner_id.display_name} if line.owner_id else False,
                'dummy_id': f"dummy_{line.id}"
            }

        # Get component move lines
        for move in self.move_raw_ids:
            for line in move.move_line_ids:
                lines.append(format_line(line, line.quantity, move.product_uom_qty, is_finished=False))
        
        # Finished product lines (the product being produced)
        byproduct_moves = self.move_byproduct_ids
        for move in self.move_finished_ids - byproduct_moves:
            for line in move.move_line_ids:
                lines.append(format_line(line, line.quantity, move.product_uom_qty, is_finished=True))

        # By-products (Register By-Products screen, like Odoo Online)
        for move in byproduct_moves.filtered(lambda m: m.state != 'cancel'):
            for line in move.move_line_ids:
                lines.append(format_line(line, line.quantity, move.product_uom_qty, is_byproduct=True))
            if not move.move_line_ids and move.state != 'done':
                # by-product without a move line yet: shown so it can be registered
                lines.append({
                    'id': 'virtual_byproduct_{}'.format(move.id),
                    'move_id': move.id,
                    'product_id': {
                        'id': move.product_id.id,
                        'display_name': move.product_id.display_name,
                        'barcode': move.product_id.barcode,
                        'tracking': move.product_id.tracking,
                    },
                    'qty_done': 0.0,
                    'quantity': 0.0,
                    'product_uom_qty': move.product_uom_qty,
                    'picked': False,
                    'is_finished_product': False,
                    'is_byproduct': True,
                    'uom_id': {'id': move.uom_id.id, 'display_name': move.uom_id.name},
                    'location_id': {'id': move.location_id.id, 'display_name': move.location_id.display_name, 'barcode': move.location_id.barcode},
                    'location_dest_id': {'id': move.location_dest_id.id, 'display_name': move.location_dest_id.display_name, 'barcode': move.location_dest_id.barcode},
                    'lot_id': False,
                    'lot_name': False,
                    'package_id': False,
                    'result_package_id': False,
                    'destination_container_package': False,
                    'dummy_id': 'virtual_byproduct_{}'.format(move.id),
                })

        return {
            'id': self.id,
            'name': self.name,
            'state': self.state,
            'quality_check_todo': getattr(self, 'quality_check_todo', False) or bool(getattr(self, 'check_ids', False)),
            'move_line_ids': lines,
            'nomenclature': nomenclature_data,
            'picking_type_id': {'id': self.picking_type_id.id, 'name': self.picking_type_id.name, 'code': self.picking_type_id.code} if self.picking_type_id else False,
            'location_id': [self.location_src_id.id, self.location_src_id.display_name] if self.location_src_id else False,
            'location_dest_id': [self.location_dest_id.id, self.location_dest_id.display_name] if self.location_dest_id else False,
            'partner_id': False,
        }

    def _barcode_get_byproduct_move(self, product_id, move_id=False, uom_id=False):
        """By-product move of this MO for the product (the given one when it matches),
        or a new one, like adding a line in the MO's By-Products tab."""
        self.ensure_one()
        open_moves = self.move_byproduct_ids.filtered(
            lambda m: m.product_id.id == product_id and m.state not in ('done', 'cancel'))
        move = open_moves.filtered(lambda m: m.id == move_id)[:1] or open_moves[:1]
        if move:
            return move
        product = self.env['product.product'].browse(product_id)
        if product == self.product_id:
            raise UserError(_("You cannot have %s as the finished product and in the Byproducts", product.display_name))
        move = self.env['stock.move'].create(self._get_move_finished_values(
            product.id, 0.0, uom_id or product.uom_id.id))
        move._action_confirm()
        return move

    def process_barcode_sync(self, commands):
        self.ensure_one()
        for cmd in commands:
            if cmd.get('action') == 'write':
                if not isinstance(cmd.get('line_id'), int):
                    continue
                line = self.env['stock.move.line'].browse(cmd.get('line_id'))
                if line.exists():
                    vals = {'quantity': cmd.get('quantity')}
                    if cmd.get('product_uom_id'):
                        vals['uom_id'] = cmd.get('product_uom_id')
                    if cmd.get('owner_id') and line.move_id in self.move_raw_ids:
                        # component consumed from stock owned by this partner (Consignment)
                        vals['owner_id'] = cmd.get('owner_id')
                    if cmd.get('package_id') and line.move_id in self.move_raw_ids:
                        # component taken from a package (Source Package)
                        pkg_id = self.env['stock.picking']._resolve_package_id(cmd.get('package_id'))
                        if pkg_id:
                            vals['package_id'] = pkg_id
                    if cmd.get('is_byproduct') and line.move_id in self.move_byproduct_ids and cmd.get('picked'):
                        # registered by hand: Odoo never recomputes picked moves when producing
                        vals['picked'] = True
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
                product_id = cmd.get('product_id')
                is_byproduct = bool(cmd.get('is_byproduct'))
                if is_byproduct:
                    if not cmd.get('quantity'):
                        continue  # nothing registered for this by-product
                    move = self._barcode_get_byproduct_move(product_id, cmd.get('move_id'), cmd.get('product_uom_id'))
                else:
                    # Try to find matching move in raw or finished
                    move = self.move_raw_ids.filtered(lambda m: m.product_id.id == product_id)
                    if not move:
                        move = self.move_finished_ids.filtered(lambda m: m.product_id.id == product_id)
                    if not move and cmd.get('quantity') and self.state not in ('done', 'cancel'):
                        # component not in the MO yet: add it, like 'Add a line' in the Components tab
                        # (its 'To Consume' is the quantity added, so an MO without BoM does not raise
                        # a consumption warning for it; with a BoM, Odoo still flags non-BoM components)
                        product = self.env['product.product'].browse(product_id).exists()
                        if product:
                            uom = self.env['uom.uom'].browse(cmd.get('product_uom_id')) if cmd.get('product_uom_id') else product.uom_id
                            move = self.env['stock.move'].create(self._get_move_raw_values(product, cmd.get('quantity'), uom))
                            move._action_confirm()
                            # Odoo may reserve the new demand right away: only the scanned line counts
                            move.move_line_ids.unlink()

                if move:
                    move = move[0]
                    vals = {
                        'move_id': move.id,
                        'product_id': product_id,
                        'quantity': cmd.get('quantity'),
                        # by-products always come from the production location
                        'location_id': move.location_id.id if is_byproduct else (cmd.get('location_id') or move.location_id.id),
                        'location_dest_id': cmd.get('location_dest_id') or move.location_dest_id.id,
                        'uom_id': cmd.get('product_uom_id') or move.uom_id.id,
                    }
                    if is_byproduct and cmd.get('picked'):
                        # registered by hand: kept as is on Produce (Odoo never recomputes picked moves)
                        vals['picked'] = True
                    if not is_byproduct and cmd.get('owner_id') and move in self.move_raw_ids:
                        vals['owner_id'] = cmd.get('owner_id')
                    if not is_byproduct and cmd.get('package_id') and move in self.move_raw_ids:
                        pkg_id = self.env['stock.picking']._resolve_package_id(cmd.get('package_id'))
                        if pkg_id:
                            vals['package_id'] = pkg_id
                    lot_id = cmd.get('lot_id')
                    lot_name = cmd.get('lot_name')
                    if lot_name and not lot_id:
                        lot = self.env['stock.lot'].search([('name', '=', lot_name), ('product_id', '=', product_id)], limit=1)
                        if not lot:
                            lot = self.env['stock.lot'].create({
                                'name': lot_name,
                                'product_id': product_id,
                                'company_id': self.company_id.id,
                            })
                        vals['lot_id'] = lot.id
                    elif lot_id:
                        vals['lot_id'] = lot_id
                    self.env['stock.move.line'].create(vals)


