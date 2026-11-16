from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.project.models.project_task import CLOSED_STATES


class ProjectTask(models.Model):
    """A task of a treatment plan's project is one phase of the plan.

    The phase lists its treatments (dental.treatment.plan.line). Its column follows the work:
    Planned, then In Progress from the first visit done, then Done once every treatment is
    completed. Moving a phase to Done records the remaining visits; cancelling it declines its
    open treatments.
    """
    _inherit = 'project.task'

    dental_plan_id = fields.Many2one(related='project_id.dental_plan_id', string='Treatment Plan', store=True)
    dental_patient_id = fields.Many2one(related='dental_plan_id.patient_id', string='Patient', store=True)
    dental_case_id = fields.Many2one(related='dental_plan_id.case_id', string='Dental Case')
    dental_plan_state = fields.Selection(related='dental_plan_id.state', string='Plan Status')
    dental_line_ids = fields.One2many('dental.treatment.plan.line', 'phase_task_id', string='Treatments')

    dental_currency_id = fields.Many2one(related='dental_plan_id.currency_id', string='Plan Currency')
    dental_amount = fields.Monetary(string='Amount', compute='_compute_dental_phase', currency_field='dental_currency_id')
    dental_progress = fields.Float(string='Progress', compute='_compute_dental_phase')
    dental_treatment_count = fields.Integer(string='Treatment Count', compute='_compute_dental_phase')
    dental_treatment_summary = fields.Char(string='Treatments Summary', compute='_compute_dental_phase')
    dental_to_invoice = fields.Boolean(string='Phase To Invoice', compute='_compute_dental_invoices')
    dental_invoice_ids = fields.Many2many('account.move', string='Phase Invoices', compute='_compute_dental_invoices')
    dental_invoice_count = fields.Integer(string='Phase Invoice Count', compute='_compute_dental_invoices')

    @api.depends('dental_line_ids.sale_line_id.qty_to_invoice', 'dental_line_ids.sale_line_id.invoice_lines')
    def _compute_dental_invoices(self):
        for task in self:
            sols = task.dental_line_ids.sale_line_id.sudo()
            task.dental_to_invoice = any(sol.qty_to_invoice > 0 and sol.order_id.state == 'sale' for sol in sols)
            invoices = sols.invoice_lines.move_id.filtered(lambda m: m.move_type in ('out_invoice', 'out_refund'))
            task.dental_invoice_ids = invoices
            task.dental_invoice_count = len(invoices)

    @api.depends('dental_line_ids.estimated_amount', 'dental_line_ids.acceptance', 'dental_line_ids.state',
                 'dental_line_ids.completed_visits', 'dental_line_ids.number_of_visits',
                 'dental_line_ids.treatment_id', 'dental_line_ids.tooth_reference')
    def _compute_dental_phase(self):
        for task in self:
            lines = task.dental_line_ids.filtered(lambda l: l.acceptance != 'declined' and l.state != 'cancelled')
            task.dental_amount = sum(lines.mapped('estimated_amount'))
            task.dental_treatment_count = len(lines)
            planned = sum(max(l.number_of_visits, 1) for l in lines)
            done = sum(max(l.number_of_visits, 1) if l.state == 'completed'
                       else min(l.completed_visits, max(l.number_of_visits, 1)) for l in lines)
            task.dental_progress = round(done * 100.0 / planned, 1) if planned else 0.0
            task.dental_treatment_summary = ', '.join(
                f"{l.treatment_id.name} · {l.tooth_reference}" if l.tooth_reference else (l.treatment_id.name or '')
                for l in lines)

    # ------------------------------------------------------------------ create / write

    @api.model_create_multi
    def create(self, vals_list):
        Project = self.env['project.project'].sudo()
        for vals in vals_list:
            project = Project.browse(vals.get('project_id') or self.env.context.get('default_project_id'))
            if project.dental_plan_id and 'sequence' not in vals:
                # A new phase goes after the plan's existing phases
                last = self.sudo().search([('project_id', '=', project.id)], order='sequence desc', limit=1)
                vals['sequence'] = (last.sequence or 0) + 1
        return super().create(vals_list)

    def write(self, vals):
        if self.env.context.get('dental_line_sync') or not ({'stage_id', 'state'} & set(vals)):
            return super().write(vals)
        phases = self.filtered('dental_plan_id')
        if not phases:
            return super().write(vals)
        Stage = self.env['project.task.type'].sudo()
        done_stage = Stage._dental_stage_for('done')
        vals = dict(vals)
        to_done_stage = vals.get('stage_id') and vals['stage_id'] == done_stage.id
        if to_done_stage and 'state' not in vals:
            vals['state'] = '1_done'
        if vals.get('state') == '1_done' and 'stage_id' not in vals and done_stage:
            vals['stage_id'] = done_stage.id
        new_state = vals.get('state')
        leaving_done = (vals.get('stage_id') and vals['stage_id'] != done_stage.id) or (
            new_state and new_state not in CLOSED_STATES)
        if leaving_done:
            completed = phases.filtered(lambda t: t.state == '1_done' and t.dental_line_ids and all(
                l.state in ('completed', 'cancelled') for l in t.dental_line_ids))
            if completed:
                raise UserError(_("Phase %s is completed: its visits are recorded and billed. Add a new phase "
                                  "instead of reopening it.", completed[0].name))
            if 'state' not in vals:
                vals['state'] = '01_in_progress'
        reopened = phases.filtered(lambda t: t.state == '1_canceled') if leaving_done else self.browse()
        res = super().write(vals)
        if new_state == '1_done':
            phases.dental_line_ids._dental_complete_remaining_visits()
        elif new_state == '1_canceled':
            for line in phases.dental_line_ids.filtered(lambda l: l.state not in ('completed', 'cancelled')):
                line.action_decline_line()
        elif reopened:
            # A cancelled phase taken back onto the board: its treatments are planned again
            reopened.dental_line_ids.filtered(lambda l: l.state == 'cancelled').write(
                {'state': 'draft', 'acceptance': 'pending'})
        return res

    def unlink(self):
        lines = self.dental_line_ids
        performed = lines.filtered(lambda l: l.session_ids.filtered(lambda s: s.state == 'completed'))
        if performed:
            raise UserError(_("%s already has visits done and cannot be deleted. Mark it done or cancel it instead.",
                              performed[0].phase_task_id.name))
        lines.unlink()
        return super().unlink()

    def _dental_refresh_phase(self):
        """Move each phase along with its treatments: In Progress from the first visit done,
        Done once every treatment is completed, Cancelled when all were declined."""
        Stage = self.env['project.task.type'].sudo()
        stages = {key: Stage._dental_stage_for(key) for key in ('planned', 'in_progress', 'done')}
        for task in self.exists().filtered('dental_plan_id'):
            all_lines = task.dental_line_ids
            lines = all_lines.filtered(lambda l: l.state != 'cancelled' and l.acceptance != 'declined')
            vals = {}
            if not lines:
                if all_lines and task.state not in CLOSED_STATES:
                    vals['state'] = '1_canceled'
            elif all(l.state == 'completed' for l in lines):
                if task.state != '1_done':
                    vals.update(state='1_done', stage_id=stages['done'].id)
            elif any(l.state in ('in_progress', 'completed') or l.completed_visits for l in lines):
                if task.stage_id in (stages['planned'] | stages['done']):
                    vals['stage_id'] = stages['in_progress'].id
                if task.state in CLOSED_STATES:
                    vals['state'] = '01_in_progress'
            if vals:
                task.sudo().with_context(dental_line_sync=True, mail_notrack=True).write(vals)

    # ------------------------------------------------------------------ actions

    def action_dental_open_plan(self):
        self.ensure_one()
        return self.dental_plan_id.action_open_form()

    def action_dental_create_invoice(self):
        """Invoice this phase only: what its treatments delivered so far, on an invoice of its own."""
        self.ensure_one()
        order = self.dental_line_ids.sale_line_id.order_id.filtered(lambda o: o.state == 'sale')[:1]
        if not order or not self.dental_to_invoice:
            raise UserError(_("Phase %s has nothing to invoice yet: record its visits first.", self.name))
        invoices = order.with_context(dental_invoice_phase_id=self.id)._create_invoices()
        return self._dental_invoice_action(invoices)

    def action_dental_view_invoices(self):
        self.ensure_one()
        return self._dental_invoice_action(self.dental_invoice_ids)

    def _dental_invoice_action(self, invoices):
        action = self.env['ir.actions.act_window']._for_xml_id('account.action_move_out_invoice_type')
        if len(invoices) == 1:
            action.update({'views': [(self.env.ref('account.view_move_form').id, 'form')], 'res_id': invoices.id})
        else:
            action['domain'] = [('id', 'in', invoices.ids)]
        action['context'] = {'default_move_type': 'out_invoice'}
        return action

    def action_dental_open_board(self):
        self.ensure_one()
        return self.dental_plan_id.action_dental_open_board()
