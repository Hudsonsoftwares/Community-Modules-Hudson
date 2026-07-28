# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class FieldServiceProductLine(models.Model):
    _name = 'field.service.product.line'
    _description = 'Field Service Product Line'
    _order = 'sequence, id'

    order_id = fields.Many2one(
        'field.service.order',
        string='Field Service Order',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(string='Sequence', default=10)
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
    )
    description = fields.Char(
        string='Description',
        compute='_compute_description',
        store=True,
        readonly=False,
    )
    quantity = fields.Float(
        string='Quantity',
        default=1.0,
        required=True,
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        compute='_compute_uom_id',
        store=True,
        readonly=False,
    )
    price_unit = fields.Float(
        string='Unit Price',
        compute='_compute_price_unit',
        store=True,
        readonly=False,
        digits='Product Price',
    )
    price_subtotal = fields.Float(
        string='Subtotal',
        compute='_compute_price_subtotal',
        store=True,
        digits='Product Price',
    )

    # ── Sale Order Line tracking ───────────────────────────────────────────────
    sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Sale Order Line',
        readonly=True,
        copy=False,
        ondelete='set null',
        help=(
            'The Sale Order line that was auto-created or linked for this product. '
            'This keeps the FS product and the SO line in sync.'
        ),
    )

    @api.depends('product_id')
    def _compute_description(self):
        for line in self:
            if line.product_id:
                line.description = line.product_id.display_name
            else:
                line.description = False

    @api.depends('product_id')
    def _compute_uom_id(self):
        for line in self:
            line.uom_id = line.product_id.uom_id if line.product_id else False

    @api.depends('product_id')
    def _compute_price_unit(self):
        for line in self:
            line.price_unit = line.product_id.lst_price if line.product_id else 0.0

    @api.depends('quantity', 'price_unit')
    def _compute_price_subtotal(self):
        for line in self:
            line.price_subtotal = line.quantity * line.price_unit

    def unlink(self):
        """Remove the linked SO line when the FS product line is deleted."""
        for line in self:
            if line.sale_order_line_id and line.sale_order_line_id.exists():
                # Only remove SO line if it was auto-created (qty_delivered == 0)
                so_line = line.sale_order_line_id
                if so_line.qty_delivered == 0 and so_line.qty_invoiced == 0:
                    so_line.sudo().unlink()
        return super().unlink()
