# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class DentalPharmacyDispense(models.Model):
    _inherit = 'dental.pharmacy.dispense'

    pos_order_id = fields.Many2one(
        'pos.order', string='POS Order', readonly=True, copy=False, index='btree_not_null',
        help='Pharmacy counter order that dispensed, billed and invoiced these medicines.')
    pos_exception = fields.Boolean(
        string='Needs Review', readonly=True, copy=False, index=True, tracking=True,
        help='The counter sale broke a pharmacy rule (expired batch, over-dispensing, prescription of another '
             'patient...). The sale was paid, so it was recorded; a pharmacy manager should review it.')
    pos_exception_note = fields.Text(string='Review Reasons', readonly=True, copy=False)
    pos_exception_reviewed = fields.Boolean(string='Reviewed', copy=False, tracking=True)

    def _dental_check_backend_allowed(self):
        """In a branch dispensing at the POS counter, the dispense form is only a manager fallback."""
        if self.env.context.get('dental_pos_sync'):
            return
        for record in self:
            if record.company_id._dental_dispenses_at_pos() and not self.env.user.has_group(
                    'dental_pharmacy.group_dental_pharmacy_manager'):
                raise UserError(_("%s dispenses and bills medicines at the Point of Sale pharmacy counter. "
                                  "Open the counter and load the prescription there.", record.company_id.name))

    def action_dispense(self):
        self._dental_check_backend_allowed()
        return super().action_dispense()

    def action_create_invoice(self):
        for record in self:
            if record.pos_order_id:
                raise UserError(_("%(disp)s was paid at the pharmacy counter and is already invoiced by POS order %(order)s.",
                                  disp=record.name, order=record.pos_order_id.name))
        return super().action_create_invoice()

    def action_return(self):
        for record in self:
            if record.pos_order_id:
                raise UserError(_("%(disp)s was sold at the pharmacy counter. Refund POS order %(order)s at the counter: "
                                  "the stock, the money and the prescription are corrected together.",
                                  disp=record.name, order=record.pos_order_id.name))
        return super().action_return()

    def action_mark_pos_exception_reviewed(self):
        if not self.env.user.has_group('dental_pharmacy.group_dental_pharmacy_manager'):
            raise UserError(_("Only a pharmacy manager can close a review."))
        for record in self:
            record.pos_exception_reviewed = True
            record.message_post(body=_("Exceptions reviewed by %s.", self.env.user.name))

    def action_view_pos_order(self):
        self.ensure_one()
        return {
            'name': _('POS Order'),
            'type': 'ir.actions.act_window',
            'res_model': 'pos.order',
            'view_mode': 'form',
            'res_id': self.pos_order_id.id,
        }


class DentalPharmacyDispenseLine(models.Model):
    _inherit = 'dental.pharmacy.dispense.line'

    pos_order_line_id = fields.Many2one('pos.order.line', string='POS Order Line', readonly=True, copy=False,
                                        index='btree_not_null')
    qty_returned = fields.Float(string='Returned Qty', readonly=True, copy=False,
                                help='Quantity refunded at the pharmacy counter.')
