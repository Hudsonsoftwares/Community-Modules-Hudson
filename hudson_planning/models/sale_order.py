# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.tools import float_compare


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    planning_slot_ids = fields.One2many('fs.planning.slot', 'sale_order_id', string='Shifts')
    planning_slot_count = fields.Integer(compute='_compute_planning_hours', string='Shifts Count')
    planning_hours_planned = fields.Float(compute='_compute_planning_hours', string='Planned Hours')
    planning_hours_to_plan = fields.Float(compute='_compute_planning_hours', string='Hours to Plan')

    @api.depends('order_line.planning_hours_planned', 'order_line.planning_hours_to_plan', 'planning_slot_ids')
    def _compute_planning_hours(self):
        for order in self:
            # sudo: salespeople see how much of their orders is planned.
            order.planning_slot_count = len(order.sudo().planning_slot_ids)
            order.planning_hours_planned = sum(order.order_line.mapped('planning_hours_planned'))
            order.planning_hours_to_plan = sum(order.order_line.mapped('planning_hours_to_plan'))

    def _action_confirm(self):
        res = super()._action_confirm()
        # sudo: salespeople confirm orders without being planning administrators.
        self.order_line.sudo()._planning_slot_generation()
        return res

    def _action_cancel(self):
        res = super()._action_cancel()
        # Shifts not planned yet are not needed anymore; planned ones are
        # kept, the planner decides what to do with them.
        self.order_line.sudo()._get_slots_to_plan().unlink()
        return res

    def action_view_planning(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('hudson_planning.action_fs_schedule_by_sale_order')
        action['context'] = {'search_default_group_resource': 1}
        planned = self.sudo().planning_slot_ids.filtered('date_start')
        if planned:
            # The shifts of the order, from the first one.
            action['context'].update(
                search_default_sale_order_id=self.id,
                initial_date=fields.Datetime.to_string(min(planned.mapped('date_start'))),
            )
        # Nothing planned yet: all the resources, to drop the shifts to plan
        # of the side panel on them.
        return action


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    planning_slot_ids = fields.One2many('fs.planning.slot', 'sale_line_id', string='Shifts')
    planning_hours_planned = fields.Float(
        compute='_compute_planning_hours', string='Planned Hours',
        help='Hours of the shifts of this line that are scheduled.',
    )
    planning_hours_to_plan = fields.Float(
        compute='_compute_planning_hours', string='Hours to Plan',
        help='Hours of this line still to schedule.',
    )

    @api.depends('planning_slot_ids.allocated_hours', 'planning_slot_ids.date_start')
    def _compute_planning_hours(self):
        for line in self:
            slots = line.sudo().planning_slot_ids
            line.planning_hours_planned = sum(slots.filtered('date_start').mapped('allocated_hours'))
            line.planning_hours_to_plan = sum(slots.filtered(lambda s: not s.date_start).mapped('allocated_hours'))

    def _is_planned_service(self):
        self.ensure_one()
        return (not self.display_type and self.product_id.planning_enabled
                and bool(self.product_id.planning_role_id) and self.state == 'sale')

    def _planning_hours_sold(self):
        """Ordered quantity, in hours (a quantity not in a time unit is taken as hours)."""
        self.ensure_one()
        uom_hour = self.env.ref('uom.product_uom_hour', raise_if_not_found=False)
        uom = self.product_uom_id
        if not uom or not uom_hour or uom == uom_hour or not uom._has_common_reference(uom_hour):
            return self.product_uom_qty
        return uom._compute_quantity(self.product_uom_qty, uom_hour, raise_if_failure=False)

    def _get_slots_to_plan(self):
        return self.planning_slot_ids.filtered(lambda s: not s.date_start)

    def _prepare_slot_to_plan_values(self, hours):
        self.ensure_one()
        order = self.order_id
        return {
            'name': self.name.split('\n')[0] if self.name else self.product_id.display_name,
            'sale_line_id': self.id,
            'sale_order_id': order.id,
            'role_id': self.product_id.planning_role_id.id,
            'allocated_hours': hours,
            'company_id': order.company_id.id,
            'project_id': self.project_id.id if 'project_id' in self._fields else False,
            'date_start': False,
            'date_end': False,
            'resource_id': False,
        }

    def _planning_slot_generation(self):
        """Keep one open shift "to plan" per planned service with the hours sold
        that are not scheduled yet (generated when the order is confirmed)."""
        Slot = self.env['fs.planning.slot'].sudo().with_context(mail_create_nolog=True, tracking_disable=True)
        for line in self:
            if not line._is_planned_service():
                continue
            rounding = 2
            slots = line.sudo().planning_slot_ids
            to_plan_slots = slots.filtered(lambda s: not s.date_start)
            planned = sum((slots - to_plan_slots).mapped('allocated_hours'))
            remaining = line._planning_hours_sold() - planned
            if float_compare(remaining, 0.0, precision_digits=rounding) <= 0:
                to_plan_slots.unlink()
            elif to_plan_slots:
                to_plan_slots[1:].unlink()
                if float_compare(to_plan_slots[0].allocated_hours, remaining, precision_digits=rounding):
                    to_plan_slots[0].allocated_hours = remaining
            else:
                Slot.create(line._prepare_slot_to_plan_values(remaining))

    def write(self, vals):
        res = super().write(vals)
        if 'product_uom_qty' in vals or 'product_uom_id' in vals:
            # Sold hours of a confirmed order changed: so do the hours to plan.
            self.sudo().filtered(lambda l: l.state == 'sale')._planning_slot_generation()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_slots_to_plan(self):
        self.sudo().with_context(planning_slot_generation=True)._get_slots_to_plan().unlink()
