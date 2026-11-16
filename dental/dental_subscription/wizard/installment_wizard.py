from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DentalInstallmentWizard(models.TransientModel):
    _name = 'dental.installment.wizard'
    _description = 'Finance a Treatment Plan with Installments'
    _check_company_auto = True

    treatment_plan_id = fields.Many2one('dental.treatment.plan', required=True, readonly=True, check_company=True)
    company_id = fields.Many2one(related='treatment_plan_id.company_id')
    currency_id = fields.Many2one(related='treatment_plan_id.currency_id')
    patient_id = fields.Many2one(related='treatment_plan_id.patient_id')
    product_id = fields.Many2one(
        'product.product', string='Installment Product', required=True, check_company=True,
        domain=[('dental_membership_type', '=', 'installment')])
    plan_id = fields.Many2one(
        'sale.subscription.plan', string='Installment Frequency', required=True, check_company=True)
    installment_count = fields.Integer(string='Number of Installments', required=True, default=12)
    amount_financed = fields.Monetary(string='Amount Financed', required=True)
    start_date = fields.Date(required=True, default=fields.Date.context_today)
    installment_amount = fields.Monetary(compute='_compute_installment_amount')
    rounding_difference = fields.Monetary(compute='_compute_installment_amount')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        plan = self.env['dental.treatment.plan'].browse(res.get('treatment_plan_id'))
        if plan:
            res.setdefault('amount_financed', plan.estimated_total)
        product = self.env['product.product'].search(
            [('dental_membership_type', '=', 'installment'),
             ('company_id', 'in', [False, (plan.company_id or self.env.company).id])], limit=1)
        if product:
            res.setdefault('product_id', product.id)
            if product.subscription_plan_id:
                res.setdefault('plan_id', product.subscription_plan_id.id)
        return res

    @api.depends('amount_financed', 'installment_count', 'currency_id')
    def _compute_installment_amount(self):
        for wizard in self:
            currency = wizard.currency_id or self.env.company.currency_id
            if wizard.installment_count > 0:
                amount = currency.round(wizard.amount_financed / wizard.installment_count)
                wizard.installment_amount = amount
                wizard.rounding_difference = currency.round(
                    wizard.amount_financed - amount * wizard.installment_count)
            else:
                wizard.installment_amount = wizard.rounding_difference = 0.0

    def action_create_installment_plan(self):
        self.ensure_one()
        plan = self.treatment_plan_id
        plan.check_access('read')
        if self.installment_count < 1:
            raise UserError(_("The number of installments must be at least 1."))
        if self.amount_financed <= 0:
            raise UserError(_("The amount financed must be positive."))
        existing = self.env['sale.order'].sudo().search([
            ('dental_treatment_plan_id', '=', plan.id), ('state', '!=', 'cancel'),
            ('subscription_state', 'in', ('draft', 'sent', '3_progress', '4_paused', '5_renew')),
        ], limit=1)
        if existing:
            raise UserError(_("%(plan)s is already financed by %(sub)s.", plan=plan.display_name, sub=existing.name))
        order = self.env['sale.order'].with_company(plan.company_id).create({
            'partner_id': plan.patient_id.id,
            'company_id': plan.company_id.id,
            'is_subscription': True,
            'plan_id': self.plan_id.id,
            'start_date': self.start_date,
            'dental_member_ids': [(6, 0, plan.patient_id.ids)],
            'dental_treatment_plan_id': plan.id,
            'dental_installment_count': self.installment_count,
            'dental_installment_total': self.amount_financed,
            'origin': plan.display_name,
            'order_line': [(0, 0, {
                'product_id': self.product_id.id,
                'name': _('%(product)s – %(plan)s (%(count)s installments)', product=self.product_id.display_name,
                          plan=plan.display_name, count=self.installment_count),
                'product_uom_qty': 1.0,
                'price_unit': self.installment_amount,
            })],
        })
        # The price set above must not be replaced by the pricelist price of the product
        order.order_line.write({'price_unit': self.installment_amount})
        plan.message_post(body=_("Installment plan %s created.", order.name))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': order.id,
        }
