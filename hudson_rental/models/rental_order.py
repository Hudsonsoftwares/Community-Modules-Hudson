# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta


class RentalOrder(models.Model):
    _name = 'rental.order'
    _description = 'Rental Order'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'date_order desc, id desc'

    name = fields.Char(string='Order Reference', required=True, copy=False, readonly=True,
                       default=lambda self: _('New'))
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, 
                                  tracking=True, readonly=True)
    date_order = fields.Datetime(string='Order Date', required=True, readonly=True,
                                  default=fields.Datetime.now, copy=False)
    pickup_date = fields.Datetime(string='Pickup Date', required=True, tracking=True)
    return_date = fields.Datetime(string='Expected Return Date', required=True, tracking=True)
    actual_return_date = fields.Datetime(string='Actual Return Date', readonly=True, copy=False)
    
    state = fields.Selection([
        ('draft', 'Quotation'),
        ('confirmed', 'Confirmed'),
        ('reserved', 'Reserved'),
        ('picked_up', 'In Progress'),
        ('returned', 'Returned'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, copy=False)
    
    order_line_ids = fields.One2many('rental.order.line', 'order_id', string='Order Lines')
    
    amount_untaxed = fields.Monetary(string='Untaxed Amount', store=True, compute='_compute_amounts', tracking=True)
    amount_tax = fields.Monetary(string='Taxes', store=True, compute='_compute_amounts')
    amount_total = fields.Monetary(string='Total', store=True, compute='_compute_amounts', tracking=True)
    amount_deposit = fields.Monetary(string='Security Deposit', compute='_compute_amounts', store=True)
    amount_late_fee = fields.Monetary(string='Late Fees', compute='_compute_late_fees', store=True)
    
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
                                   default=lambda self: self.env.company.currency_id)
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                  default=lambda self: self.env.company)
    
    user_id = fields.Many2one('res.users', string='Salesperson', default=lambda self: self.env.user,
                              tracking=True)
    
    sale_order_id = fields.Many2one('sale.order', string='Sales Order', readonly=True, copy=False)
    invoice_ids = fields.One2many('account.move', 'rental_order_id', string='Invoices', readonly=True)
    invoice_count = fields.Integer(string='Invoice Count', compute='_compute_invoice_count')
    invoice_status = fields.Selection([
        ('no', 'Nothing to Invoice'),
        ('to_invoice', 'To Invoice'),
        ('invoiced', 'Fully Invoiced'),
    ], string='Invoice Status', compute='_compute_invoice_status', store=True)
    
    picking_ids = fields.One2many('stock.picking', 'rental_order_id', string='Transfers')
    delivery_count = fields.Integer(string='Delivery Count', compute='_compute_delivery_count')
    
    note = fields.Text(string='Terms and Conditions')
    
    @api.model
    def create(self, vals):
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('rental.order') or _('New')
        return super(RentalOrder, self).create(vals)

    @api.depends('order_line_ids.price_total', 'order_line_ids.price_tax', 'order_line_ids.deposit_amount')
    def _compute_amounts(self):
        for order in self:
            amount_untaxed = sum(order.order_line_ids.mapped('price_subtotal'))
            amount_tax = sum(order.order_line_ids.mapped('price_tax'))
            amount_deposit = sum(order.order_line_ids.mapped('deposit_amount'))
            
            order.update({
                'amount_untaxed': amount_untaxed,
                'amount_tax': amount_tax,
                'amount_total': amount_untaxed + amount_tax,
                'amount_deposit': amount_deposit,
            })

    @api.depends('actual_return_date', 'return_date', 'order_line_ids.late_fee')
    def _compute_late_fees(self):
        for order in self:
            order.amount_late_fee = sum(order.order_line_ids.mapped('late_fee'))

    @api.depends('invoice_ids')
    def _compute_invoice_count(self):
        for order in self:
            order.invoice_count = len(order.invoice_ids)

    @api.depends('order_line_ids.qty_invoiced', 'order_line_ids.quantity', 'state')
    def _compute_invoice_status(self):
        for order in self:
            if order.state in ['draft', 'cancel']:
                order.invoice_status = 'no'
            elif any(line.quantity != line.qty_invoiced for line in order.order_line_ids):
                order.invoice_status = 'to_invoice'
            else:
                order.invoice_status = 'invoiced'

    @api.depends('picking_ids')
    def _compute_delivery_count(self):
        for order in self:
            order.delivery_count = len(order.picking_ids)

    @api.constrains('pickup_date', 'return_date')
    def _check_dates(self):
        for order in self:
            if order.return_date <= order.pickup_date:
                raise ValidationError(_('Return date must be after pickup date'))

    def action_confirm(self):
        for order in self:
            if not order.order_line_ids:
                raise UserError(_('Cannot confirm a rental order without lines'))
            order.state = 'confirmed'
            order._create_sale_order()

    def action_reserve(self):
        for order in self:
            # Check stock availability
            for line in order.order_line_ids:
                if line.product_id.type == 'product':
                    available = line.product_id.with_context(
                        location=order.company_id.rental_location_id.id
                    ).qty_available
                    if available < line.quantity:
                        raise UserError(_('Not enough stock available for %s') % line.product_id.name)
            
            order.state = 'reserved'
            order._create_delivery()

    def action_pickup(self):
        return {
            'name': _('Confirm Pickup'),
            'type': 'ir.actions.act_window',
            'res_model': 'rental.pickup.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id}
        }

    def action_return(self):
        return {
            'name': _('Process Return'),
            'type': 'ir.actions.act_window',
            'res_model': 'rental.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id}
        }

    def action_extend(self):
        return {
            'name': _('Extend Rental'),
            'type': 'ir.actions.act_window',
            'res_model': 'rental.extend.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_order_id': self.id}
        }

    def action_done(self):
        for order in self:
            if order.invoice_status != 'invoiced':
                raise UserError(_('Please invoice the order before marking it as done'))
            order.state = 'done'

    def action_cancel(self):
        for order in self:
            order.state = 'cancel'

    def action_view_invoice(self):
        invoices = self.invoice_ids
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_move_out_invoice_type')
        if len(invoices) > 1:
            action['domain'] = [('id', 'in', invoices.ids)]
        elif len(invoices) == 1:
            action['views'] = [(self.env.ref('account.view_move_form').id, 'form')]
            action['res_id'] = invoices.id
        else:
            action = {'type': 'ir.actions.act_window_close'}
        return action

    def action_view_delivery(self):
        action = self.env['ir.actions.act_window']._for_xml_id('stock.action_picking_tree_all')
        pickings = self.picking_ids
        if len(pickings) > 1:
            action['domain'] = [('id', 'in', pickings.ids)]
        elif pickings:
            action['views'] = [(self.env.ref('stock.view_picking_form').id, 'form')]
            action['res_id'] = pickings.id
        return action

    def _create_sale_order(self):
        """Create a sale order for invoicing purposes"""
        for order in self:
            if not order.sale_order_id:
                sale_vals = {
                    'partner_id': order.partner_id.id,
                    'date_order': order.date_order,
                    'user_id': order.user_id.id,
                    'company_id': order.company_id.id,
                    'origin': order.name,
                    'note': order.note,
                }
                sale_order = self.env['sale.order'].create(sale_vals)
                order.sale_order_id = sale_order.id

    def _create_delivery(self):
        """Create stock picking for rental pickup"""
        StockPicking = self.env['stock.picking']
        for order in self:
            if not order.company_id.rental_use_transfers:
                continue
            if not order.company_id.rental_location_id:
                raise UserError(_('Please configure rental location in settings'))
            
            picking_vals = {
                'partner_id': order.partner_id.id,
                'origin': order.name,
                'rental_order_id': order.id,
                'picking_type_id': order.company_id.rental_picking_type_id.id,
                'location_id': order.company_id.rental_location_id.id,
                'location_dest_id': order.partner_id.property_stock_customer.id,
                'scheduled_date': order.pickup_date,
            }
            picking = StockPicking.create(picking_vals)
            
            # Create moves for each line
            for line in order.order_line_ids:
                if line.product_id.type == 'product':
                    self.env['stock.move'].create({
                        'name': line.product_id.name,
                        'product_id': line.product_id.id,
                        'product_uom_qty': line.quantity,
                        'product_uom': line.product_uom.id,
                        'picking_id': picking.id,
                        'location_id': order.company_id.rental_location_id.id,
                        'location_dest_id': order.partner_id.property_stock_customer.id,
                    })

    def action_create_invoice(self):
        """Create invoice for rental charges"""
        self.ensure_one()
        
        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_date': fields.Date.context_today(self),
            'invoice_origin': self.name,
            'rental_order_id': self.id,
            'invoice_line_ids': [],
        }
        
        for line in self.order_line_ids.filtered(lambda l: l.quantity > l.qty_invoiced):
            invoice_line_vals = {
                'product_id': line.product_id.id,
                'name': line.name,
                'quantity': line.quantity - line.qty_invoiced,
                'price_unit': line.price_unit,
                'tax_ids': [(6, 0, line.tax_id.ids)],
            }
            invoice_vals['invoice_line_ids'].append((0, 0, invoice_line_vals))
        
        # Add late fees if any
        if self.amount_late_fee > 0:
            late_fee_product = self.env.ref('hudson_rental.product_late_fee', raise_if_not_found=False)
            if late_fee_product:
                invoice_vals['invoice_line_ids'].append((0, 0, {
                    'product_id': late_fee_product.id,
                    'name': 'Late Return Fee',
                    'quantity': 1,
                    'price_unit': self.amount_late_fee,
                }))
        
        invoice = self.env['account.move'].create(invoice_vals)
        
        # Update invoiced quantities
        for line in self.order_line_ids:
            line.qty_invoiced = line.quantity
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': invoice.id,
        }

    def _get_portal_return_url(self):
        self.ensure_one()
        return '/my/rentals/%s' % self.id
