# pyrefly: ignore [missing-import]
from odoo import _, models
from odoo.exceptions import UserError


class StockPickingBatch(models.Model):
    _inherit = "stock.picking.batch"

    def action_client_action(self):
        """'Barcode' smart button of the batch form: open this batch in the Barcode app."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'custom_barcode_client_action',
            'name': self.name,
            'target': 'fullscreen',
            'params': {'batch_id': self.id},
        }

    def get_barcode_view_state(self):
        """
        Returns structured batch state for the Barcode frontend.
        Preserves individual picking/move-line identity — never merges quantities across pickings.
        """
        self.ensure_one()

        pickings_data = []
        move_lines_data = []

        grouped_lines = {}
        for picking in self.picking_ids:
            pickings_data.append({
                "id": picking.id,
                "name": picking.name,
                "state": picking.state,
                "partner_id": {
                    "id": picking.partner_id.id,
                    "display_name": picking.partner_id.display_name,
                } if picking.partner_id else False,
                "location_id": {
                    "id": picking.location_id.id,
                    "display_name": picking.location_id.display_name,
                    "barcode": picking.location_id.barcode,
                } if picking.location_id else False,
                "location_dest_id": {
                    "id": picking.location_dest_id.id,
                    "display_name": picking.location_dest_id.display_name,
                    "barcode": picking.location_dest_id.barcode,
                } if picking.location_dest_id else False,
            })

            for line in picking.move_line_ids:
                # same as single transfers: 0-unit lines of open moves are covered by the
                # move's remaining-demand line
                if line.uom_id.is_zero(line.quantity) and line.move_id and line.move_id.state not in ('done', 'cancel'):
                    continue
                tracking = line.product_id.tracking if line.product_id else 'none'
                key = (
                    picking.id,
                    line.product_id.id if line.product_id else False,
                    line.location_id.id if line.location_id else False,
                    line.location_dest_id.id if line.location_dest_id else False,
                    line.lot_id.id if line.lot_id else False,
                    line.package_id.id if line.package_id else False,
                    line.result_package_id.id if line.result_package_id else False,
                    line.result_package_id.parent_package_id.id if (line.result_package_id and line.result_package_id.parent_package_id) else False,
                )
                
                if tracking == 'serial':
                    key = ('serial', picking.id, line.id)
                    
                if key not in grouped_lines:
                    grouped_lines[key] = {
                        "id": line.id,
                        "move_id": line.move_id.id if line.move_id else False,
                        "picking_id": {
                            "id": picking.id,
                            "name": picking.name,
                        },
                        "product_id": {
                            "id": line.product_id.id,
                            "display_name": line.product_id.display_name,
                            "barcode": line.product_id.barcode,
                            "tracking": tracking,
                        } if line.product_id else False,
                        "qty_done": line.quantity,
                        "quantity": line.quantity,
                        "product_uom_qty": line.quantity_product_uom,
                        "picked": line.picked,
                        "uom_id": {
                            "id": line.uom_id.id,
                            "display_name": line.uom_id.name,
                        } if line.uom_id else False,
                        "location_id": {
                            "id": line.location_id.id,
                            "display_name": line.location_id.display_name,
                            "barcode": line.location_id.barcode,
                        } if line.location_id else False,
                        "location_dest_id": {
                            "id": line.location_dest_id.id,
                            "display_name": line.location_dest_id.display_name,
                            "barcode": line.location_dest_id.barcode,
                        } if line.location_dest_id else False,
                        "lot_id": {
                            "id": line.lot_id.id,
                            "name": line.lot_id.name,
                        } if line.lot_id else False,
                        "lot_name": line.lot_name,
                        "package_id": {
                            "id": line.package_id.id,
                            "name": line.package_id.name,
                            "path": line.package_id.complete_name,
                        } if line.package_id else False,
                        "result_package_id": {
                            "id": line.result_package_id.id,
                            "name": line.result_package_id.name,
                            "path": line.result_package_id.dest_complete_name,
                        } if line.result_package_id else False,
                        "dummy_id": "dummy_{}".format(line.id),
                    }
                else:
                    grouped_lines[key]['qty_done'] += line.quantity
                    grouped_lines[key]['quantity'] += line.quantity
                    grouped_lines[key]['product_uom_qty'] += line.quantity_product_uom
                    grouped_lines[key]['picked'] = grouped_lines[key]['picked'] or line.picked

        # Demand not covered by move lines (moves without lines, or the rest after packing part
        # of a move): show it as its own line, tagged with its transfer, like on single transfers.
        for picking in self.picking_ids:
            for move in picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                remaining = move.product_uom_qty - move.quantity if move.move_line_ids else move.product_uom_qty
                if move.uom_id.compare(remaining, 0) <= 0:
                    continue
                grouped_lines[('remaining', move.id)] = {
                    "id": "virtual_{}".format(move.id),
                    "move_id": move.id,
                    "picking_id": {"id": picking.id, "name": picking.name},
                    "product_id": {
                        "id": move.product_id.id,
                        "display_name": move.product_id.display_name,
                        "barcode": move.product_id.barcode,
                        "tracking": move.product_id.tracking,
                    } if move.product_id else False,
                    "qty_done": 0.0,
                    "quantity": 0.0,
                    "product_uom_qty": remaining,
                    "picked": False,
                    "uom_id": {"id": move.uom_id.id, "display_name": move.uom_id.name} if move.uom_id else False,
                    "location_id": {"id": move.location_id.id, "display_name": move.location_id.display_name, "barcode": move.location_id.barcode} if move.location_id else False,
                    "location_dest_id": {"id": move.location_dest_id.id, "display_name": move.location_dest_id.display_name, "barcode": move.location_dest_id.barcode} if move.location_dest_id else False,
                    "lot_id": False,
                    "lot_name": False,
                    "package_id": False,
                    "result_package_id": False,
                    "dummy_id": "virtual_{}".format(move.id),
                }

        move_lines_data = list(grouped_lines.values())

        # Barcode nomenclature rules (the scanner needs them to classify scanned barcodes)
        nomenclature = self.env.company.nomenclature_id
        nomenclature_data = [{
            'name': rule.name, 'type': rule.type, 'pattern': rule.pattern, 'sequence': rule.sequence,
        } for rule in nomenclature.rule_ids] if nomenclature else []

        # Odoo 20: stock.group_reception_report no longer exists; the feature is enabled per
        # operation type (auto_show_allocation_report), already part of `show_allocation`.
        show_allocation = any(getattr(p, 'show_allocation', False) for p in self.picking_ids)

        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "show_allocation": show_allocation,
            "scheduled_date": str(self.scheduled_date) if self.scheduled_date else False,
            "responsible_id": {
                "id": self.user_id.id,
                "display_name": self.user_id.display_name,
            } if self.user_id else False,
            "pickings": pickings_data,
            "move_lines": move_lines_data,
            "nomenclature": nomenclature_data,
        }

    def process_barcode_sync(self, commands):
        """
        Routes barcode sync commands to the correct individual picking.
        Each command must include picking_id so we know which picking to write to.
        """
        self.ensure_one()
        by_picking = {}
        for cmd in commands:
            pid = cmd.get("picking_id")
            if pid not in by_picking:
                by_picking[pid] = []
            by_picking[pid].append(cmd)

        for picking_id, cmds in by_picking.items():
            picking = self.env["stock.picking"].browse(picking_id)
            if picking.exists() and picking.batch_id.id == self.id:
                clean_cmds = [{k: v for k, v in c.items() if k != "picking_id"} for c in cmds]
                picking.process_barcode_sync(clean_cmds)

    def action_barcode_create_return(self):
        """Return Products on a done batch: create the return of each done transfer
        (same rules as on a single transfer). Transfers with nothing left to return are
        skipped. Several returns of the same operation type are grouped in a new batch so
        they can be scanned together.
        Returns {'picking_id': id} | {'batch_id': id, 'name': name} | {'picking_ids': ids}."""
        self.ensure_one()
        returns = self.env['stock.picking']
        for picking in self.picking_ids.filtered(lambda p: p.state == 'done'):
            try:
                with self.env.cr.savepoint():
                    returns |= self.env['stock.picking'].browse(picking.action_barcode_create_return())
            except UserError:
                # nothing left to return on this transfer (already fully returned)
                continue
        if not returns:
            raise UserError(_("There is nothing left to return in this batch."))
        if len(returns) == 1:
            return {'picking_id': returns.id}
        if len(returns.picking_type_id) == 1 and len(returns.company_id) == 1:
            batch = self.create({
                'picking_type_id': returns.picking_type_id.id,
                'company_id': returns.company_id.id,
                'user_id': self.env.user.id,
                'picking_ids': [(6, 0, returns.ids)],
            })
            batch.action_confirm()
            return {'batch_id': batch.id, 'name': batch.name}
        return {'picking_ids': returns.ids}
