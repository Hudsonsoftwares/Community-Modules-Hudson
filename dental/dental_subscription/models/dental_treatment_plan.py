from odoo import _, fields, models
from odoo.exceptions import UserError


class DentalTreatmentPlan(models.Model):
    _inherit = 'dental.treatment.plan'

    dental_installment_ids = fields.One2many(
        'sale.order', 'dental_treatment_plan_id', string='Installment Plans', readonly=True)
    dental_installment_count = fields.Integer(compute='_compute_dental_installment', compute_sudo=True)
    is_dental_financed = fields.Boolean(
        string='Financed by Installments', compute='_compute_dental_installment', compute_sudo=True)

    def _compute_dental_installment(self):
        for plan in self:
            orders = plan.sudo().dental_installment_ids.filtered(lambda o: o.state != 'cancel')
            plan.dental_installment_count = len(orders)
            plan.is_dental_financed = any(o.state == 'sale' and o._dental_benefits_usable_on(
                fields.Date.context_today(plan))[0] for o in orders)

    def action_dental_finance_installments(self):
        self.ensure_one()
        if self.state in ('draft', 'cancelled'):
            raise UserError(_("Propose or approve the treatment plan before financing it."))
        return {
            'name': _('Finance with Installments'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.installment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_treatment_plan_id': self.id},
        }

    def action_dental_view_installments(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('dental_subscription.action_dental_subscriptions')
        action['domain'] = [('dental_treatment_plan_id', '=', self.id)]
        action['context'] = {'create': False}
        return action
