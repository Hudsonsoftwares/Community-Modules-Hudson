# -*- coding: utf-8 -*-
"""Picked-up rentals now leave the stock (to the company's Rental location) until their
return. Units picked up before this version are still counted On Hand: move them out."""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env['sale.order.line'].search([
        ('is_rental', '=', True), ('state', '=', 'sale'), ('qty_delivered', '>', 0)])
    items = []
    for line in lines:
        # With Rental Transfers, pickups already made a delivery to the customer
        if line.order_id.company_id.rental_use_transfers or not line.product_id.is_storable:
            continue
        out_qty = line.qty_delivered - line.qty_returned
        if line.product_uom_id.compare(out_qty, 0) <= 0 or line._rented_out_moves():
            continue
        lots = line.pickedup_lot_ids - line.returned_lot_ids
        items.append((line, len(lots) if lots else out_qty, lots))
    moves = env['sale.order.line']._rental_move_stock(items, pickup=True)
    _logger.info("hudson_rental: moved %s rented-out line(s) out of the stock", len(moves))
