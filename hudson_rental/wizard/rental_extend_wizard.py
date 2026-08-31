# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class RentalExtendWizard(models.TransientModel):
    _name = 'rental.extend.wizard'
    _description = 'Rental Extension Wizard'

    order_id = fields.Many2one('rental.order', string='Rental Order', required=True)
    current_return_date = fields.Datetime(related='order_id.return_date', readonly=True)
    new_return_date = fields.Datetime(string='New Return Date', required=True)
    extension_days = fields.Float(string='Extension (Days)', compute='_compute_extension', store=True)
    extension_cost = fields.Float(string='Extension Cost', compute='_compute_extension_cost', store=True)
    currency_id = fields.Many2one(related='order_id.currency_id', readonly=True)
    note = fields.Text(string='Reason for Extension')

    @api.depends('current_return_date', 'new_return_date')
    def _compute_extension(self):
        for wizard in self:
            if wizard.current_return_date and wizard.new_return_date:
                if wizard.new_return_date <= wizard.current_return_date:
                    wizard.extension_days = 0.0
                else:
                    delta = wizard.new_return_date - wizard.current_return_date
                    wizard.extension_days = delta.days + (delta.seconds / 86400.0)
            else:
                wizard.extension_days = 0.0

    @api.depends('extension_days', 'order_id.order_line_ids')
    def _compute_extension_cost(self):
        for wizard in self:
            total_cost = 0.0
            for line in wizard.order_id.order_line_ids:
                price = line.product_id.product_tmpl_id.get_rental_price(wizard.extension_days, 'day')
                total_cost += price * line.quantity
            wizard.extension_cost = total_cost

    @api.constrains('new_return_date', 'current_return_date')
    def _check_dates(self):
        for wizard in self:
            if wizard.new_return_date <= wizard.current_return_date:
                raise ValidationError(_('New return date must be after current return date'))

    def action_extend_rental(self):
        self.ensure_one()
        
        if self.order_id.state not in ['picked_up', 'reserved']:
            raise UserError(_('Can only extend active rentals'))
        
        # Update return date
        self.order_id.write({
            'return_date': self.new_return_date,
        })
        
        # Recalculate prices
        for line in self.order_id.order_line_ids:
            line._compute_duration()
            line._onchange_price_unit()
        
        # Log message
        self.order_id.message_post(
            body=_('Rental extended by %s days. New return date: %s') % (
                round(self.extension_days, 1),
                self.new_return_date.strftime('%Y-%m-%d %H:%M')
            )
        )
        
        return {'type': 'ir.actions.act_window_close'}
