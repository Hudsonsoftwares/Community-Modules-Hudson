from odoo import fields, models

# Context key: invoice only the order lines of this phase (project.task id; False = lines of no phase)
PHASE_KEY = 'dental_invoice_phase_id'


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    dental_plan_id = fields.Many2one('dental.treatment.plan', string='Treatment Plan', copy=False,
                                     index='btree_not_null', readonly=True)

    def action_dental_open_plan(self):
        self.ensure_one()
        return self.dental_plan_id.action_open_form()

    def _get_invoiceable_lines(self, final=False):
        lines = super()._get_invoiceable_lines(final)
        if PHASE_KEY in self.env.context:
            phase_id = self.env.context[PHASE_KEY] or False
            lines = lines.filtered(lambda l: l.task_id.id == phase_id)
        return lines

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        phase = self.env['project.task'].browse(self.env.context.get(PHASE_KEY) or [])
        if phase:
            vals['invoice_origin'] = f"{self.name} · {phase.name}"
        return vals

    def _create_invoices(self, final=False, grouped=False):
        """A treatment plan's order is invoiced phase by phase: one invoice per phase, never one
        invoice mixing several phases (also from the order's own Create Invoice button)."""
        dental = self.filtered('dental_plan_id')
        if PHASE_KEY in self.env.context or not dental:
            return super()._create_invoices(final=final, grouped=grouped)
        moves = self.env['account.move']
        if self - dental:
            moves |= super(SaleOrder, self - dental)._create_invoices(final=final, grouped=grouped)
        for order in dental:
            lines = order._get_invoiceable_lines(final).filtered(lambda l: not l.display_type)
            phases = lines.task_id.sorted(lambda t: (t.sequence, t.id))
            keys = phases.ids + ([False] if lines.filtered(lambda l: not l.task_id) else [])
            if not keys:
                # Nothing to invoice: the standard behaviour (and its message)
                moves |= super(SaleOrder, order)._create_invoices(final=final, grouped=grouped)
            for key in keys:
                moves |= super(SaleOrder, order.with_context(**{PHASE_KEY: key}))._create_invoices(
                    final=final, grouped=True)
        return moves


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    dental_plan_line_id = fields.Many2one('dental.treatment.plan.line', string='Plan Treatment', copy=False,
                                          index='btree_not_null', readonly=True)
