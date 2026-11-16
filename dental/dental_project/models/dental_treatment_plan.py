from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.dental_core.models.dental_treatment_plan import TREATMENT_PHASES

# Treatment fields that make up its sales order line
SALE_SYNC_FIELDS = {'treatment_id', 'tooth_reference', 'quantity', 'unit_price', 'discount', 'phase_task_id'}


def _without_defaults(context):
    """Context without the calling form's default_* keys (default_stage_id of a board column,
    default_case_id of the case...): they belong to that form's model, not to the records
    created here."""
    return {k: v for k, v in context.items() if not k.startswith('default_')}


class DentalTreatmentPlan(models.Model):
    """A treatment plan is a project; each task of the project is one phase of the plan.

    A phase holds the treatments done in it (dental.treatment.plan.line, which stay the clinical
    and billing records: visits, invoicing, orthodontics... all keep working on them).
    """
    _inherit = 'dental.treatment.plan'

    project_id = fields.Many2one('project.project', string='Treatment Board', copy=False, readonly=True,
                                 index='btree_not_null')
    dental_phase_ids = fields.One2many('project.task', 'dental_plan_id', string='Phases')
    sale_order_id = fields.Many2one('sale.order', string='Sales Order', copy=False, readonly=True,
                                    index='btree_not_null')
    sale_order_state = fields.Selection(related='sale_order_id.state', string='Sales Order Status', tracking=False)
    dental_steps_to_quote = fields.Boolean(compute='_compute_dental_steps_to_quote')

    @api.depends('line_ids.sale_line_id', 'line_ids.acceptance', 'line_ids.state', 'state', 'sale_order_id.state')
    def _compute_dental_steps_to_quote(self):
        for plan in self:
            plan.dental_steps_to_quote = bool(plan._dental_lines_to_quote())

    @api.depends('line_ids.state', 'line_ids.acceptance', 'dental_phase_ids.state')
    def _compute_step_summary(self):
        # Plan cards count phases (the board's cards), not individual treatments
        for plan in self:
            phases = plan.dental_phase_ids.filtered(lambda t: t.state != '1_canceled')
            done = phases.filtered(lambda t: t.state == '1_done')
            plan.step_count = len(phases)
            plan.step_done_count = len(done)
            plan.step_summary = (_('%(done)s of %(total)s phases done', done=len(done), total=len(phases))
                                 if phases else _('No phases yet'))

    @api.model_create_multi
    def create(self, vals_list):
        plans = super().create(vals_list)
        plans._dental_ensure_project()
        return plans

    def write(self, vals):
        res = super().write(vals)
        if {'patient_id', 'doctor_id'} & set(vals):
            for plan in self.filtered('project_id'):
                plan.project_id.sudo().write(plan._dental_project_vals(update=True))
        return res

    # ------------------------------------------------------------------ project

    def _dental_project_vals(self, update=False):
        self.ensure_one()
        vals = {
            'name': f"{self.name} · {self.patient_id.name}" if self.patient_id else self.name,
            'partner_id': self.patient_id.id,
            'user_id': self.doctor_id.user_id.id or False,
        }
        if not update:
            vals.update({
                'dental_plan_id': self.id,
                'company_id': self.company_id.id,
                'privacy_visibility': 'employees',
                'label_tasks': _('Phases'),
                'allow_billable': True,  # keeps each phase's task linked to its sales order lines
                'type_ids': [fields.Command.set(self.env['project.task.type'].sudo()._dental_board_stages().ids)],
            })
        return vals

    def _dental_ensure_project(self):
        """Project of each plan (created on first use); treatments without a phase get one."""
        Project = self.env['project.project'].sudo().with_context(_without_defaults(self.env.context))
        for plan in self.filtered(lambda p: not p.project_id):
            plan.sudo().project_id = Project.create(plan._dental_project_vals())
        self.line_ids.filtered(lambda l: not l.phase_task_id)._dental_assign_phase()

    def action_dental_open_board(self):
        """The plan's phases on a board (Planned / In Progress / Done)."""
        self.ensure_one()
        self._dental_ensure_project()
        return {
            'name': _('Treatment Plan · %s', self.display_name),
            'type': 'ir.actions.act_window',
            'res_model': 'project.task',
            'view_mode': 'kanban,list,form',
            'views': [
                (self.env.ref('dental_project.view_task_kanban_dental').id, 'kanban'),
                (self.env.ref('dental_project.view_task_list_dental').id, 'list'),
                (self.env.ref('dental_project.view_task_form_dental').id, 'form'),
            ],
            'search_view_id': [self.env.ref('dental_project.view_task_search_dental').id],
            'domain': [('project_id', '=', self.project_id.id)],
            'context': {
                'default_project_id': self.project_id.id,
                'default_partner_id': self.patient_id.id,
                'default_user_ids': [fields.Command.set(self.doctor_id.user_id.ids)] if self.doctor_id.user_id else False,
                'active_id': self.project_id.id,
                'project_kanban': True,  # every column shows, even when empty
            },
            'target': 'current',
        }

    # ------------------------------------------------------------------ sales order

    def _dental_lines_to_quote(self):
        """Treatments not on the sales order yet: every undeclined one while the plan is an estimate,
        accepted ones once the patient accepted. Treatments already billed with direct invoices stay
        on that path, so nothing is billed twice."""
        self.ensure_one()
        estimate = self.state in ('draft', 'proposed')
        return self.line_ids.filtered(lambda l: (
            not l.sale_line_id
            and l.state != 'cancelled'
            and (l.acceptance != 'declined' if estimate else l.acceptance == 'accepted')
            and not l.session_ids._get_active_invoice_lines()
        ))

    def _dental_prepare_sale_order_vals(self):
        self.ensure_one()
        return {
            'partner_id': self.patient_id.id,
            'company_id': self.company_id.id,
            'origin': self.name,
            'dental_plan_id': self.id,
            'user_id': self.env.user.id,
            'note': self.notes or False,
        }

    def _dental_sync_sale_order(self, confirm=False):
        """Create or complete the plan's sales order (one line per treatment) and confirm it when asked."""
        SaleOrder = self.env['sale.order'].sudo().with_context(_without_defaults(self.env.context))
        for plan in self:
            lines = plan._dental_lines_to_quote()
            order = plan.sale_order_id.sudo()
            if order.state == 'cancel':
                order = SaleOrder
            if not order and not lines:
                continue
            if not order:
                order = SaleOrder.create(plan._dental_prepare_sale_order_vals())
                plan.sudo().sale_order_id = order
            for line in lines.sorted(lambda l: (l.phase_task_id.sequence, l.phase_task_id.id, l.id)):
                line._dental_create_sale_line(order)
            if confirm and order.state in ('draft', 'sent'):
                order.action_confirm()
            plan.line_ids._dental_update_delivered()

    def action_dental_create_quotation(self):
        """Quotation for the plan (estimate to the patient); accepting the plan confirms it."""
        self.ensure_one()
        if not self._dental_lines_to_quote() and not self.sale_order_id:
            raise UserError(_("Plan %s has no treatment to quote yet.", self.name))
        self._dental_sync_sale_order()
        return self.action_dental_view_sale_order()

    def action_dental_view_sale_order(self):
        self.ensure_one()
        return {
            'name': self.sale_order_id.name,
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.sale_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_accept(self):
        res = super().action_accept()
        self._dental_sync_sale_order(confirm=True)
        return res

    def action_decline(self):
        res = super().action_decline()
        for order in self.sale_order_id.sudo().filtered(lambda o: o.state in ('draft', 'sent')):
            order._action_cancel()
        self.dental_phase_ids._dental_refresh_phase()
        return res

    def action_reset_to_draft(self):
        res = super().action_reset_to_draft()
        # Phases cancelled with the plan come back to the board
        self.dental_phase_ids.filtered(lambda t: t.state == '1_canceled').with_context(
            dental_line_sync=True).write({'state': '01_in_progress'})
        return res


class DentalTreatmentPlanLine(models.Model):
    """One treatment of a phase."""
    _inherit = 'dental.treatment.plan.line'

    phase_task_id = fields.Many2one('project.task', string='Phase', copy=False, index='btree_not_null',
                                    ondelete='cascade', domain="[('dental_plan_id', '=', plan_id)]")
    sale_line_id = fields.Many2one('sale.order.line', string='Sales Order Line', copy=False, readonly=True,
                                   index='btree_not_null')

    @api.model_create_multi
    def create(self, vals_list):
        Task = self.env['project.task'].sudo()
        for vals in vals_list:
            # Added inside a phase: the plan is the phase's plan
            if vals.get('phase_task_id') and not vals.get('plan_id'):
                vals['plan_id'] = Task.browse(vals['phase_task_id']).dental_plan_id.id
        lines = super().create(vals_list)
        # New treatment on a plan whose earlier phases were all finished: the plan goes on
        lines.plan_id.filtered(lambda p: p.state == 'completed').write({'state': 'in_progress'})
        lines.filtered(lambda l: not l.phase_task_id)._dental_assign_phase()
        # Added to a plan the patient already accepted: part of the agreed treatment, on its order
        late = lines.filtered(lambda l: l.plan_id.state in ('approved', 'in_progress') and l.acceptance == 'pending')
        if late:
            late.write({'acceptance': 'accepted'})
            late.plan_id._dental_sync_sale_order(confirm=True)
        lines.phase_task_id._dental_refresh_phase()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if SALE_SYNC_FIELDS & set(vals):
            self.filtered('sale_line_id')._dental_update_sale_line()
        return res

    def unlink(self):
        for line in self.filtered('sale_line_id'):
            sol = line.sale_line_id.sudo()
            if sol.qty_invoiced or sol.qty_delivered:
                raise UserError(_("%s is already billed on %s; cancel it instead of deleting it.",
                                  line.display_name, sol.order_id.name))
            if sol.order_id.state in ('draft', 'sent'):
                sol.unlink()
            else:
                sol.product_uom_qty = 0.0
        return super().unlink()

    # ------------------------------------------------------------------ phase

    def _dental_assign_phase(self):
        """Treatments created outside a phase (plan form, orthodontics...): into the phase named after
        their clinical phase, created on the board when missing."""
        Task = self.env['project.task'].sudo().with_context(
            _without_defaults(self.env.context), dental_line_sync=True, mail_create_nolog=True)
        planned = self.env['project.task.type'].sudo()._dental_stage_for('planned')
        labels = dict(TREATMENT_PHASES)
        for line in self.filtered(lambda l: not l.phase_task_id):
            plan = line.plan_id
            if not plan.project_id:
                plan._dental_ensure_project()  # assigns this line too
                continue
            phase_key = line.phase or '3'
            name = labels.get(phase_key, phase_key)
            phase = plan.project_id.sudo().task_ids.filtered(lambda t: t.name == name)[:1]
            if not phase:
                phase = Task.create({
                    'name': name,
                    'project_id': plan.project_id.id,
                    'partner_id': plan.patient_id.id,
                    'stage_id': planned.id,
                    'sequence': int(phase_key) if phase_key.isdigit() else 10,
                    'user_ids': [fields.Command.set(plan.doctor_id.user_id.ids)],
                })
            line.sudo().phase_task_id = phase

    def _dental_complete_remaining_visits(self):
        """The phase was marked done: record the remaining visits of its treatments as done."""
        for line in self.filtered(lambda l: l.state not in ('completed', 'cancelled') and l.acceptance != 'declined'):
            for _visit in range(max(line.number_of_visits, 1) + 1):
                if line.state in ('completed', 'cancelled'):
                    break
                line.action_mark_visit_done()

    # ------------------------------------------------------------------ sales order line

    def _dental_sale_line_label(self):
        self.ensure_one()
        name = self.treatment_id.name or _('Treatment')
        if self.tooth_reference:
            name = _('%(treatment)s · Tooth %(tooth)s', treatment=name, tooth=self.tooth_reference)
        if self.phase_task_id:
            name = f"{name} · {self.phase_task_id.name}"
        return f"{name} ({self.plan_id.name})"

    def _dental_create_sale_line(self, order):
        self.ensure_one()
        product = self.treatment_id.product_variant_id
        if not product:
            raise UserError(_("Treatment %s has no product to sell.", self.treatment_id.display_name))
        sol = self.env['sale.order.line'].sudo().create({
            'order_id': order.id,
            'product_id': product.id,
            'name': self._dental_sale_line_label(),
            'product_uom_qty': self.quantity,
            'price_unit': self.unit_price,
            'discount': self.discount,
            'dental_plan_line_id': self.id,
            'task_id': self.phase_task_id.id or False,
        })
        self.sudo().sale_line_id = sol
        return sol

    def _dental_update_sale_line(self):
        for line in self:
            sol = line.sale_line_id.sudo()
            if sol.qty_invoiced or sol.order_id.state == 'cancel':
                continue
            vals = {}
            if sol.product_id != line.treatment_id.product_variant_id and line.treatment_id.product_variant_id:
                vals['product_id'] = line.treatment_id.product_variant_id.id
            vals.update({
                'name': line._dental_sale_line_label(),
                'product_uom_qty': max(line.quantity, sol.qty_delivered),
                'price_unit': line.unit_price,
                'discount': line.discount,
                'task_id': line.phase_task_id.id or False,
            })
            sol.write(vals)

    def _dental_update_delivered(self):
        """Delivered quantity of the sales order line follows the visits done (progress billing)."""
        for line in self.filtered('sale_line_id'):
            sol = line.sale_line_id.sudo()
            if sol.order_id.state != 'sale' or sol.qty_delivered_method != 'manual':
                continue
            visits = max(line.number_of_visits, 1)
            if line.state == 'completed':
                delivered = line.quantity
            else:
                delivered = round(line.quantity * min(line.completed_visits, visits) / visits, 2)
            if sol.qty_delivered != delivered:
                sol.qty_delivered = delivered

    # ------------------------------------------------------------------ workflow hooks

    def _update_progress_from_sessions(self):
        res = super()._update_progress_from_sessions()
        self._dental_update_delivered()
        self.phase_task_id._dental_refresh_phase()
        return res

    def action_accept_line(self):
        res = super().action_accept_line()
        self.plan_id.filtered(lambda p: p.sale_order_id or p.state not in ('draft', 'proposed'))._dental_sync_sale_order(
            confirm=True)
        return res

    def action_decline_line(self):
        res = super().action_decline_line()
        for line in self.filtered('sale_line_id'):
            sol = line.sale_line_id.sudo()
            if sol.order_id.state in ('draft', 'sent'):
                line.sudo().sale_line_id = False
                sol.unlink()
            elif not sol.qty_invoiced:
                sol.product_uom_qty = sol.qty_delivered
        self.phase_task_id._dental_refresh_phase()
        return res


class DentalTreatmentSession(models.Model):
    _inherit = 'dental.treatment.session'

    billing_state = fields.Selection(selection_add=[('sale_order', 'On Sales Order')])

    @api.depends('state', 'invoice_line_ids.move_id.state', 'plan_line_id.sale_line_id.order_id.state')
    def _compute_billing_state(self):
        super()._compute_billing_state()
        for session in self:
            sol = session.plan_line_id.sale_line_id
            if session.billing_state == 'to_invoice' and sol and sol.order_id.state != 'cancel':
                # Billed through the plan's sales order, never with a direct invoice as well
                session.billing_state = 'sale_order'
