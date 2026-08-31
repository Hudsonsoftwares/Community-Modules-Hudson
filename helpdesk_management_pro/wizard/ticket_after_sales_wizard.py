# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class HelpdeskTicketRefund(models.TransientModel):
    _name = 'helpdesk.ticket.refund'
    _description = 'Refund Wizard'

    ticket_id = fields.Many2one('helpdesk.management.ticket', required=True)
    sale_order_id = fields.Many2one('sale.order', string='Sales Order')
    product_id = fields.Many2one('product.product', string='Product')
    lot_id = fields.Many2one('stock.lot', string='Lot/Serial Number')
    journal_id = fields.Many2one('account.journal', string='Journal', domain=[('type', 'in', ['sale', 'bank', 'cash'])])
    reversal_date = fields.Date(string='Reversal date', default=fields.Date.context_today)

    def action_reverse(self):
        # Implementation for processing the refund
        return {'type': 'ir.actions.act_window_close'}


class HelpdeskTicketGiftcard(models.TransientModel):
    _name = 'helpdesk.ticket.giftcard'
    _description = 'Gift Card Wizard'

    ticket_id = fields.Many2one('helpdesk.management.ticket', required=True)
    program_id = fields.Many2one('loyalty.program', string='Program', domain=[('program_type', '=', 'gift_card')])
    gift_card_value = fields.Float(string='Gift Card value', default=1.00)
    valid_until = fields.Date(string='Valid Until')
    description = fields.Char(string='Description', default='Example: Gift for customer')

    def action_generate(self):
        # Implementation for generating gift card
        return {'type': 'ir.actions.act_window_close'}


class HelpdeskTicketCoupon(models.TransientModel):
    _name = 'helpdesk.ticket.coupon'
    _description = 'Coupon Wizard'

    ticket_id = fields.Many2one('helpdesk.management.ticket', required=True)
    program_id = fields.Many2one('loyalty.program', string='Coupon Program', domain=[('program_type', '=', 'coupons')])
    valid_until = fields.Date(string='Valid Until')

    def action_send_email(self):
        # Implementation for sending coupon email
        return {'type': 'ir.actions.act_window_close'}

    def action_get_share_link(self):
        # Implementation for getting share link
        return {'type': 'ir.actions.act_window_close'}


class HelpdeskTicketReturn(models.TransientModel):
    _name = 'helpdesk.ticket.return'
    _description = 'Return Wizard'

    ticket_id = fields.Many2one('helpdesk.management.ticket', required=True)
    sale_order_id = fields.Many2one('sale.order', string='Sales Order')
    picking_id = fields.Many2one('stock.picking', string='Delivery to Return', domain="[('sale_id', '=', sale_order_id), ('state', '=', 'done')]")

    def action_return(self):
        # Trigger the standard stock return picking wizard
        self.ensure_one()
        if not self.picking_id:
            return {'type': 'ir.actions.act_window_close'}
        
        return {
            'name': _('Reverse Transfer'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.return.picking',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.picking_id.id,
                'active_ids': [self.picking_id.id],
                'active_model': 'stock.picking',
            }
        }
