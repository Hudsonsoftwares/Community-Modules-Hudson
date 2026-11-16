import logging

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import format_amount

from .product_template import DENTAL_SUBSCRIPTION_TYPES
from .subscription_benefit import PERIOD_DELTA

_logger = logging.getLogger(__name__)

# hudson_subscriptions states of a contract that is still running
RUNNING_STATES = ('3_progress', '4_paused', '5_renew')
# states in which membership benefits can be used (paused contracts give no benefits)
BENEFIT_STATES = ('3_progress', '5_renew')
PAYMENT_STATUS = [
    ('not_invoiced', 'Not Invoiced'),
    ('draft', 'Draft Invoice'),
    ('due', 'Payment Due'),
    ('overdue', 'Overdue'),
    ('paid', 'Paid'),
]


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ------------------------------------------------------------------
    # Type & members
    # ------------------------------------------------------------------
    dental_subscription_type = fields.Selection(
        DENTAL_SUBSCRIPTION_TYPES, string='Dental Subscription Type',
        compute='_compute_dental_subscription_type', store=True, index=True)
    is_dental_subscription = fields.Boolean(
        string='Dental Subscription', compute='_compute_dental_subscription_type', store=True, index=True)
    dental_max_members = fields.Integer(string='Members Allowed', compute='_compute_dental_max_members')
    dental_member_ids = fields.Many2many(
        'res.partner', 'sale_order_dental_member_rel', 'order_id', 'partner_id',
        string='Covered Members', domain=[('is_dental_patient', '=', True)],
        help='Existing dental patients covered by this subscription.')
    dental_member_count = fields.Integer(string='Members', compute='_compute_dental_member_count')

    # ------------------------------------------------------------------
    # Benefits
    # ------------------------------------------------------------------
    dental_benefit_ids = fields.One2many(
        'dental.subscription.benefit', 'order_id', string='Benefits', copy=False)
    dental_benefits_active = fields.Boolean(
        string='Benefits Usable', compute='_compute_dental_benefit_status', compute_sudo=True)
    dental_benefit_status = fields.Char(
        string='Benefit Status', compute='_compute_dental_benefit_status', compute_sudo=True)

    # ------------------------------------------------------------------
    # Orthodontic installments
    # ------------------------------------------------------------------
    dental_treatment_plan_id = fields.Many2one(
        'dental.treatment.plan', string='Financed Treatment Plan', check_company=True,
        index='btree_not_null', copy=False, tracking=True,
        help='Treatment plan paid through this installment plan. Its sessions are billed at zero.')
    dental_installment_count = fields.Integer(string='Number of Installments', copy=False, tracking=True)
    dental_installment_total = fields.Monetary(string='Amount Financed', copy=False)
    dental_installments_billed = fields.Integer(
        string='Installments Invoiced', compute='_compute_dental_payment', compute_sudo=True)

    # ------------------------------------------------------------------
    # Payments & reminders
    # ------------------------------------------------------------------
    dental_payment_status = fields.Selection(
        PAYMENT_STATUS, string='Payment Status', compute='_compute_dental_payment', compute_sudo=True)
    dental_amount_due = fields.Monetary(string='Amount Due', compute='_compute_dental_payment', compute_sudo=True)
    dental_amount_overdue = fields.Monetary(string='Amount Overdue', compute='_compute_dental_payment', compute_sudo=True)
    dental_overdue_since = fields.Date(string='Overdue Since', compute='_compute_dental_payment', compute_sudo=True)
    dental_expiry_reminder_date = fields.Date(string='Expiry Reminder Sent', copy=False, readonly=True)
    dental_overdue_reminder_date = fields.Date(string='Last Payment Reminder', copy=False, readonly=True)

    # ==================================================================
    # Computes
    # ==================================================================
    @api.depends('order_line.product_id.dental_membership_type', 'order_line.product_id.dental_max_members',
                 'is_subscription')
    def _compute_dental_subscription_type(self):
        for order in self:
            templates = order.order_line.product_id.product_tmpl_id.filtered('dental_membership_type')
            order.dental_subscription_type = templates[:1].dental_membership_type
            order.is_dental_subscription = bool(templates) and order.is_subscription

    @api.depends('order_line.product_id.dental_max_members')
    def _compute_dental_max_members(self):
        for order in self:
            templates = order.order_line.product_id.product_tmpl_id.filtered('dental_membership_type')
            order.dental_max_members = max(templates.mapped('dental_max_members') or [0])

    @api.depends('dental_member_ids')
    def _compute_dental_member_count(self):
        for order in self:
            order.dental_member_count = len(order.dental_member_ids)

    def _compute_dental_benefit_status(self):
        today = fields.Date.context_today(self)
        for order in self:
            if not order.is_dental_subscription:
                order.dental_benefits_active, order.dental_benefit_status = False, False
                continue
            order.dental_benefits_active, order.dental_benefit_status = order._dental_benefits_usable_on(today)

    def _compute_dental_payment(self):
        today = fields.Date.context_today(self)
        dental = self.filtered(lambda o: o.is_dental_subscription and o.id)
        invoices_by_order = dental._dental_get_invoices_by_order()
        for order in self:
            invoices = invoices_by_order.get(order.id, self.env['account.move'])
            posted = invoices.filtered(lambda m: m.state == 'posted')
            open_invoices = posted.filtered(
                lambda m: m.payment_state not in ('paid', 'in_payment', 'reversed') and m.amount_residual > 0)
            overdue = open_invoices.filtered(lambda m: m.invoice_date_due and m.invoice_date_due < today)
            order.dental_installments_billed = len(invoices)
            order.dental_amount_due = sum(open_invoices.mapped('amount_residual'))
            order.dental_amount_overdue = sum(overdue.mapped('amount_residual'))
            order.dental_overdue_since = min(overdue.mapped('invoice_date_due')) if overdue else False
            if not order.is_dental_subscription:
                order.dental_payment_status = False
            elif overdue:
                order.dental_payment_status = 'overdue'
            elif open_invoices:
                order.dental_payment_status = 'due'
            elif posted:
                order.dental_payment_status = 'paid'
            elif invoices:
                order.dental_payment_status = 'draft'
            else:
                order.dental_payment_status = 'not_invoiced'

    # ==================================================================
    # Invoices of a subscription (initial invoice + recurring invoices)
    # ==================================================================
    def _dental_get_invoices_by_order(self):
        """{order_id: active customer invoices}, read in batch.

        The first invoice is linked through the order lines (standard sale flow), recurring
        ones are created by hudson_subscriptions with ``subscription_order_id``.
        """
        result = {}
        if not self:
            return result
        Move = self.env['account.move'].sudo()
        recurring = Move.search([('subscription_order_id', 'in', self.ids), ('move_type', '=', 'out_invoice'),
                                 ('state', '!=', 'cancel')])
        for order in self.sudo():
            moves = order.invoice_ids | recurring.filtered(lambda m: m.subscription_order_id.id == order.id)
            result[order.id] = moves.filtered(lambda m: m.move_type == 'out_invoice' and m.state != 'cancel')
        return result

    def _dental_get_invoices(self):
        self.ensure_one()
        return self._dental_get_invoices_by_order().get(self.id, self.env['account.move'])

    # ==================================================================
    # Benefit eligibility
    # ==================================================================
    def _dental_is_completed_installment(self):
        self.ensure_one()
        reason = self.env.ref('dental_subscription.close_reason_installments_completed', raise_if_not_found=False)
        return self.subscription_state == '6_churn' and reason and self.close_reason_id == reason

    def _dental_benefits_usable_on(self, on_date):
        """(usable, explanation) for using this subscription's benefits on ``on_date``."""
        self.ensure_one()
        if self.state != 'sale' or self.is_upsell:
            return False, _('Not confirmed')
        if self.dental_subscription_type == 'installment':
            # The financed treatment stays covered once every installment is billed: payment
            # collection of the installments is followed up separately (overdue reminders).
            if self.subscription_state in RUNNING_STATES or self._dental_is_completed_installment():
                return True, _('Treatment plan financed')
            return False, _('Installment plan closed')
        if self.subscription_state not in BENEFIT_STATES:
            label = dict(self._fields['subscription_state'].selection).get(
                self.subscription_state, self.subscription_state)
            return False, _('Subscription %s', label)
        if self.start_date and on_date < self.start_date:
            return False, _('Starts on %s', self.start_date)
        if self.end_date and on_date > self.end_date:
            return False, _('Expired on %s', self.end_date)
        overdue_since = self.dental_overdue_since
        if overdue_since:
            grace = max(self.plan_id.auto_close_limit or 0, 0)
            if on_date > overdue_since + relativedelta(days=grace):
                return False, _('Suspended: payment overdue since %s', overdue_since)
        return True, _('Active')

    # ==================================================================
    # Onchange / constraints
    # ==================================================================
    @api.onchange('partner_id', 'order_line')
    def _onchange_dental_members(self):
        if self.dental_subscription_type and not self.dental_member_ids and self.partner_id.is_dental_patient:
            self.dental_member_ids = self.partner_id

    @api.constrains('order_line', 'dental_member_ids')
    def _check_dental_subscription(self):
        for order in self.filtered('is_dental_subscription'):
            types = set(order.order_line.product_id.product_tmpl_id.filtered('dental_membership_type')
                        .mapped('dental_membership_type'))
            if len(types) > 1:
                raise ValidationError(_(
                    "%s mixes several dental subscription types. Sell each membership or package on its own subscription.",
                    order.name))
            non_patients = order.dental_member_ids.filtered(lambda p: not p.is_dental_patient)
            if non_patients:
                raise ValidationError(_(
                    "Only registered dental patients can be covered: %s is not a patient.",
                    ', '.join(non_patients.mapped('display_name'))))
            if len(order.dental_member_ids) > order.dental_max_members:
                raise ValidationError(_(
                    "%(order)s covers %(count)s members but its product allows %(max)s.",
                    order=order.name, count=len(order.dental_member_ids), max=order.dental_max_members))

    def _dental_check_duplicates(self):
        """One running subscription of a type per patient and branch; one financing per treatment plan.

        Searched with sudo so another salesperson's contract cannot be missed; only its reference is shown.
        """
        for order in self.filtered('is_dental_subscription'):
            if order.is_upsell:
                continue
            start = order.start_date or fields.Date.context_today(order)
            domain = [
                ('id', 'not in', (order | order.origin_order_id).ids),
                ('is_dental_subscription', '=', True),
                ('is_upsell', '=', False),
                ('state', '=', 'sale'),
                ('subscription_state', 'in', RUNNING_STATES),
                ('company_id', '=', order.company_id.id),
                '|', ('end_date', '=', False), ('end_date', '>=', start),
            ]
            if order.dental_subscription_type == 'installment':
                if not order.dental_treatment_plan_id:
                    continue
                duplicate = self.sudo().search(
                    domain + [('dental_treatment_plan_id', '=', order.dental_treatment_plan_id.id)], limit=1)
                if duplicate:
                    raise ValidationError(_(
                        "Treatment plan %(plan)s is already financed by installment plan %(sub)s.",
                        plan=order.dental_treatment_plan_id.display_name, sub=duplicate.name))
                continue
            for member in order.dental_member_ids:
                duplicate = self.sudo().search(domain + [
                    ('dental_subscription_type', '=', order.dental_subscription_type),
                    ('dental_member_ids', 'in', member.id),
                ], limit=1)
                if duplicate:
                    type_label = dict(DENTAL_SUBSCRIPTION_TYPES)[order.dental_subscription_type]
                    raise ValidationError(_(
                        "%(patient)s already has a running %(type)s at this branch (%(sub)s). "
                        "Renew or upsell that subscription instead of creating a new one.",
                        patient=member.display_name, type=type_label, sub=duplicate.name))

    # ==================================================================
    # Lifecycle
    # ==================================================================
    def _dental_prepare_confirmation(self):
        for order in self:
            if not order.dental_member_ids and order.partner_id.is_dental_patient:
                order.dental_member_ids = order.partner_id
            if not order.dental_member_ids:
                raise UserError(_(
                    "%s: add the covered patient(s) before confirming. The customer is not a registered dental patient.",
                    order.name))
            if order.dental_subscription_type == 'installment' and not order.is_upsell:
                plan = order.dental_treatment_plan_id
                if not plan:
                    raise UserError(_(
                        "%s: link the treatment plan financed by this installment plan "
                        "(use 'Finance with Installments' on the treatment plan).", order.name))
                if plan.patient_id not in order.dental_member_ids:
                    raise UserError(_("The patient of %s must be the covered member.", plan.display_name))
                if order.dental_installment_count < 1:
                    raise UserError(_("%s: set the number of installments.", order.name))
        self._dental_check_duplicates()

    def action_confirm(self):
        dental = self.filtered('is_dental_subscription')
        dental._dental_prepare_confirmation()
        res = super().action_confirm()
        dental._dental_sync_benefits()
        for order in dental.filtered(lambda o: o.dental_subscription_type == 'installment'
                                     and not o.end_date and o.plan_id and o.dental_installment_count):
            order.end_date = order._dental_installment_end_date()
        return res

    def write(self, vals):
        res = super().write(vals)
        if 'dental_member_ids' in vals or 'dental_treatment_plan_id' in vals:
            self.filtered(lambda o: o.is_dental_subscription and o.state == 'sale')._dental_check_duplicates()
        return res

    def _dental_installment_end_date(self):
        """Last day covered by the final installment."""
        self.ensure_one()
        plan = self.plan_id
        step = PERIOD_DELTA.get(plan.billing_period_unit, PERIOD_DELTA['months'])
        start = self.start_date or fields.Date.context_today(self)
        return start + step(plan.billing_period_value * self.dental_installment_count) - relativedelta(days=1)

    def _dental_sync_benefits(self):
        """Copy the product benefit rules onto the contract once, when it is confirmed.

        Later changes to the catalog do not alter running contracts; renewals get the current rules.
        """
        Benefit = self.env['dental.subscription.benefit']
        for order in self:
            if order.dental_benefit_ids or order.is_upsell:
                continue
            vals_list = [rule._prepare_subscription_benefit_vals(order)
                         for rule in order.order_line.product_id.product_tmpl_id.dental_benefit_rule_ids]
            if order.dental_subscription_type == 'installment' and order.dental_treatment_plan_id:
                vals_list.append({
                    'order_id': order.id,
                    'sequence': 0,
                    'name': _('Sessions of %s', order.dental_treatment_plan_id.display_name),
                    'benefit_type': 'covered',
                    'quantity_limit': 0,
                    'limit_period': 'term',
                    'treatment_plan_id': order.dental_treatment_plan_id.id,
                })
            if vals_list:
                Benefit.create(vals_list)

    def action_dental_reload_benefits(self):
        """Re-copy the product benefit rules (only while no benefit has been used)."""
        for order in self:
            if order.dental_benefit_ids.usage_line_ids:
                raise UserError(_("%s: benefits already used cannot be reloaded. Edit them instead.", order.name))
            order.dental_benefit_ids.unlink()
        self._dental_sync_benefits()
        return True

    def _create_subscription_invoice(self, automatic=False):
        """Serialize recurring billing per contract and stop installment plans at their last installment."""
        self.ensure_one()
        if not self.is_dental_subscription:
            return super()._create_subscription_invoice(automatic=automatic)
        # The cron and a user clicking "Create Invoice" must never bill the same period twice
        self.env.cr.execute("SELECT id FROM sale_order WHERE id = %s FOR UPDATE", [self.id])
        self.invalidate_recordset(['next_invoice_date', 'subscription_state'])
        is_installment = self.dental_subscription_type == 'installment' and self.dental_installment_count
        billed = len(self._dental_get_invoices()) if is_installment else 0
        if is_installment and billed >= self.dental_installment_count:
            raise UserError(_("All %(count)s installments of %(name)s are already invoiced.",
                              count=self.dental_installment_count, name=self.name))
        invoice = super()._create_subscription_invoice(automatic=automatic)
        if is_installment and billed + 1 >= self.dental_installment_count:
            self._dental_close_completed_installments()
        return invoice

    def _dental_close_completed_installments(self):
        reason = self.env.ref('dental_subscription.close_reason_installments_completed')
        today = fields.Date.context_today(self)
        for order in self:
            order.write({
                'subscription_state': '6_churn',
                'close_reason_id': reason.id,
                'close_date': today,
                'end_date': order.end_date or today,
            })
            order.message_post(body=Markup(_(
                "Last installment invoiced: the installment plan is <b>completed</b>. "
                "Sessions of the financed treatment plan remain covered.")))

    # ==================================================================
    # Billing integration (called from account.move._dental_create_or_extend_invoice)
    # ==================================================================
    @api.model
    def _dental_apply_membership_benefits(self, patient, company, line_vals):
        """Apply the best usable benefit of the patient's subscriptions (same branch only) to each line.

        A covered line is kept on the invoice with a 100% discount so the visit stays traceable.
        """
        if not patient or not line_vals:
            return line_vals
        today = fields.Date.context_today(self)
        orders = self.sudo().search([
            ('is_dental_subscription', '=', True),
            ('state', '=', 'sale'),
            ('company_id', '=', company.id),
            ('dental_member_ids', 'in', patient.id),
        ])
        orders = orders.filtered(lambda o: o._dental_benefits_usable_on(today)[0])
        if not orders:
            return line_vals
        # Serialize consumption of limited benefits across concurrent billing
        self.env.cr.execute("SELECT id FROM sale_order WHERE id IN %s FOR UPDATE", [tuple(orders.ids)])
        benefits = orders.dental_benefit_ids
        Product = self.env['product.product'].sudo()
        Session = self.env['dental.treatment.session'].sudo()
        pending = {}
        result = []
        for vals in line_vals:
            vals = dict(vals)
            product = Product.browse(vals.get('product_id')) if vals.get('product_id') else Product
            session = Session.browse(vals['dental_session_id']) if vals.get('dental_session_id') else Session
            qty = vals.get('quantity', 1.0) or 1.0
            best = self.env['dental.subscription.benefit']
            for benefit in benefits:
                if not benefit._applies_to_line(product.product_tmpl_id, session):
                    continue
                if benefit._remaining_on(today, pending.get(benefit.id, 0.0)) < qty:
                    continue
                if not best or benefit._get_discount() > best._get_discount():
                    best = benefit
            if best and best._get_discount() > (vals.get('discount') or 0.0):
                pending[best.id] = pending.get(best.id, 0.0) + qty
                vals['discount'] = best._get_discount()
                vals['dental_subscription_benefit_id'] = best.id
                label = _('covered by %s', best.order_id.name) if best.benefit_type == 'covered' \
                    else _('%(discount)s%% membership discount (%(sub)s)', discount=round(best.discount, 2),
                           sub=best.order_id.name)
                vals['name'] = '%s – %s' % (vals.get('name') or product.display_name, label)
            result.append(vals)
        return result

    # ==================================================================
    # Daily lifecycle: expiry, renewal reminders, overdue reminders
    # ==================================================================
    @api.model
    def _cron_dental_subscription_lifecycle(self):
        today = fields.Date.context_today(self)
        orders = self.search([
            ('is_dental_subscription', '=', True),
            ('is_upsell', '=', False),
            ('state', '=', 'sale'),
            ('subscription_state', 'in', RUNNING_STATES),
        ])
        _logger.info("Dental subscriptions: daily lifecycle check of %d contracts", len(orders))
        for order in orders:
            try:
                with self.env.cr.savepoint():
                    order._dental_process_lifecycle(today)
            except Exception:
                _logger.exception("Dental subscription lifecycle failed for %s", order.name)

    def _dental_process_lifecycle(self, today):
        self.ensure_one()
        plan = self.plan_id
        renewable = self.dental_subscription_type != 'installment'
        # 1. Expired: benefits stop, the contract waits for renewal
        if renewable and self.end_date and self.end_date < today and self.subscription_state in ('3_progress', '4_paused'):
            self.subscription_state = '5_renew'
            self.message_post(body=Markup(_("Subscription expired on %s and is now <b>To Renew</b>.")) % self.end_date)
        # 2. Renewal not done within the grace period: close as expired
        grace = max(plan.auto_close_limit or 0, 0)
        if renewable and self.subscription_state == '5_renew' and self.end_date \
                and self.end_date + relativedelta(days=grace) < today:
            reason = self.env.ref('dental_subscription.close_reason_membership_expired')
            self.write({'subscription_state': '6_churn', 'close_reason_id': reason.id, 'close_date': today})
            self.message_post(body=Markup(_("Not renewed within %s days after expiry: subscription <b>closed</b>.")) % grace)
            return
        # 3. Expiry reminder (once per contract)
        days = plan.dental_expiry_reminder_days
        if renewable and days > 0 and self.end_date and not self.dental_expiry_reminder_date \
                and today <= self.end_date <= today + relativedelta(days=days) \
                and not self.child_order_ids.filtered(lambda o: o.is_renewal and o.state == 'sale'):
            self._dental_send_template('dental_subscription.mail_template_subscription_expiry')
            self.dental_expiry_reminder_date = today
            self.activity_schedule(
                'mail.mail_activity_data_todo', date_deadline=self.end_date,
                summary=_('Membership renewal due'),
                note=_('%s ends on %s. Offer the renewal to the patient.', self.name, self.end_date),
                user_id=self.user_id.id or self.env.user.id)
        # 4. Overdue payment reminder, repeated every N days while overdue
        interval = plan.dental_overdue_reminder_days
        if interval > 0 and self.dental_amount_overdue > 0 and (
                not self.dental_overdue_reminder_date
                or self.dental_overdue_reminder_date + relativedelta(days=interval) <= today):
            first = not self.dental_overdue_reminder_date
            self._dental_send_template('dental_subscription.mail_template_subscription_overdue')
            self.dental_overdue_reminder_date = today
            if first:
                self.activity_schedule(
                    'mail.mail_activity_data_todo', date_deadline=today,
                    summary=_('Membership payment overdue'),
                    note=_('%(sub)s has %(amount)s overdue since %(date)s.', sub=self.name,
                           amount=format_amount(self.env, self.dental_amount_overdue, self.currency_id),
                           date=self.dental_overdue_since),
                    user_id=self.user_id.id or self.env.user.id)
        elif not self.dental_amount_overdue and self.dental_overdue_reminder_date:
            self.dental_overdue_reminder_date = False

    def _dental_send_template(self, xmlid):
        template = self.env.ref(xmlid, raise_if_not_found=False)
        if template and self.partner_id.email:
            self.message_post_with_source(template, subtype_xmlid='mail.mt_comment')
        elif template:
            self.message_post(body=_("Reminder '%s' not emailed: the subscriber has no email address.", template.name))

    # ==================================================================
    # Actions
    # ==================================================================
    def action_dental_view_benefits(self):
        self.ensure_one()
        return {
            'name': _('Benefits – %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.subscription.benefit',
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
            'context': {'default_order_id': self.id},
        }

    def action_dental_view_members(self):
        self.ensure_one()
        return {
            'name': _('Covered Members'),
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.dental_member_ids.ids)],
            'context': {'create': False},
        }

    # ==================================================================
    # Admin dashboard
    # ==================================================================
    @api.model
    def _dental_check_dashboard_access(self):
        user = self.env.user
        if not (user.has_group('dental_subscription.group_membership_manager')
                or user.has_group('dental_base.group_dental_manager')):
            raise AccessError(_("Only clinic managers and membership managers can open the membership dashboard."))

    @api.model
    def get_dental_subscription_dashboard(self, branch_id=None):
        """Live, branch-scoped membership statistics (one RPC for the whole dashboard).

        Runs with sudo after the access and branch checks of dental_base/SECURITY.md §4;
        every query is filtered on the checked branch.
        """
        self._dental_check_dashboard_access()
        company = self.env['res.company'].browse(branch_id) if branch_id else self.env.company
        self.env['dental.company.mixin']._dental_check_company_access(company)
        Order = self.sudo().with_company(company)
        Move = self.env['account.move'].sudo()
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        currency = company.currency_id
        completed_reason = self.env.ref('dental_subscription.close_reason_installments_completed')

        base = [('is_dental_subscription', '=', True), ('company_id', '=', company.id), ('is_upsell', '=', False)]
        confirmed = base + [('state', '=', 'sale')]
        running = confirmed + [('subscription_state', 'in', RUNNING_STATES)]
        active_dom = confirmed + [('subscription_state', '=', '3_progress')]
        expiring_dom = running + [('dental_subscription_type', '!=', 'installment'),
                                  ('end_date', '>=', fields.Date.to_string(today)),
                                  ('end_date', '<=', fields.Date.to_string(today + relativedelta(days=30)))]
        new_dom = confirmed + [('is_renewal', '=', False),
                               ('start_date', '>=', fields.Date.to_string(month_start)),
                               ('start_date', '<=', fields.Date.to_string(today))]
        churn_dom = confirmed + [('subscription_state', '=', '6_churn'),
                                 ('close_date', '>=', fields.Date.to_string(month_start)),
                                 ('close_reason_id', '!=', completed_reason.id)]
        renewed_dom = confirmed + [('is_renewal', '=', True),
                                   ('start_date', '>=', fields.Date.to_string(month_start))]

        active = Order.search(active_dom)
        running_orders = Order.search(running)
        mrr = sum(active.mapped('recurring_monthly'))

        invoice_dom = [
            ('move_type', '=', 'out_invoice'), ('company_id', '=', company.id),
            '|', ('subscription_order_id.is_dental_subscription', '=', True),
                 ('invoice_line_ids.sale_line_ids.order_id.is_dental_subscription', '=', True),
        ]
        overdue_inv_dom = invoice_dom + [
            ('state', '=', 'posted'), ('payment_state', 'not in', ('paid', 'in_payment', 'reversed')),
            ('amount_residual', '>', 0), ('invoice_date_due', '<', fields.Date.to_string(today))]
        draft_inv_dom = invoice_dom + [('state', '=', 'draft')]
        month_inv_dom = invoice_dom + [('state', '=', 'posted'),
                                       ('invoice_date', '>=', fields.Date.to_string(month_start))]
        overdue_invoices = Move.search(overdue_inv_dom)
        month_invoices = Move.search(month_inv_dom)
        posted_invoice_ids = Move.search(invoice_dom + [('state', '=', 'posted')]).ids

        # Money actually collected this month on subscription invoices (reconciliations, credit notes excluded)
        collected = 0.0
        if posted_invoice_ids:
            partials = self.env['account.partial.reconcile'].sudo().search([
                ('debit_move_id.move_id', 'in', posted_invoice_ids),
                ('credit_move_id.move_id.move_type', '!=', 'out_refund'),
                ('max_date', '>=', month_start), ('max_date', '<=', today),
            ])
            collected = sum(partials.mapped('amount'))

        usage_dom = [('dental_subscription_benefit_id', '!=', False), ('company_id', '=', company.id),
                     ('parent_state', '!=', 'cancel'),
                     ('move_id.invoice_date', '>=', fields.Date.to_string(month_start))]
        usage_lines = self.env['account.move.line'].sudo().search(usage_dom)
        benefit_value = sum(l.price_unit * l.quantity * (l.discount or 0.0) / 100.0 for l in usage_lines)

        overdue_orders = running_orders.filtered(lambda o: o.dental_amount_overdue > 0)
        suspended = running_orders.filtered(
            lambda o: o.dental_subscription_type != 'installment' and o.subscription_state in BENEFIT_STATES
            and not o.dental_benefits_active)

        type_labels = dict(DENTAL_SUBSCRIPTION_TYPES)
        by_type = []
        for sub_type, label in DENTAL_SUBSCRIPTION_TYPES:
            orders = running_orders.filtered(lambda o: o.dental_subscription_type == sub_type)
            by_type.append({
                'key': sub_type, 'label': label, 'count': len(orders),
                'members': len(orders.dental_member_ids),
                'mrr': sum(orders.filtered(lambda o: o.subscription_state == '3_progress').mapped('recurring_monthly')),
                'domain': running + [('dental_subscription_type', '=', sub_type)],
            })

        # Six-month trend: new contracts, churn and invoiced amount per month
        trend = []
        for offset in range(5, -1, -1):
            m_start = month_start - relativedelta(months=offset)
            m_end = m_start + relativedelta(months=1)
            m_new = Order.search_count(confirmed + [
                ('is_renewal', '=', False), ('start_date', '>=', m_start), ('start_date', '<', m_end)])
            m_churn = Order.search_count(confirmed + [
                ('subscription_state', '=', '6_churn'), ('close_reason_id', '!=', completed_reason.id),
                ('close_date', '>=', m_start), ('close_date', '<', m_end)])
            m_invoiced = sum(Move.search(invoice_dom + [
                ('state', '=', 'posted'), ('invoice_date', '>=', m_start), ('invoice_date', '<', m_end)
            ]).mapped('amount_total_signed'))
            trend.append({'label': m_start.strftime('%b %Y'), 'new': m_new, 'churn': m_churn,
                          'invoiced': m_invoiced})

        def order_row(order):
            return {
                'id': order.id, 'name': order.name, 'partner': order.partner_id.display_name,
                'type': type_labels.get(order.dental_subscription_type, ''),
                'plan': order.plan_id.name or '',
                'end_date': fields.Date.to_string(order.end_date) if order.end_date else '',
                'next_invoice_date': fields.Date.to_string(order.next_invoice_date) if order.next_invoice_date else '',
                'amount_overdue': order.dental_amount_overdue,
                'overdue_since': fields.Date.to_string(order.dental_overdue_since) if order.dental_overdue_since else '',
                'members': order.dental_member_count,
                'state': order.subscription_state,
            }

        expiring = Order.search(expiring_dom, order='end_date asc', limit=8)
        overdue_rows = sorted(overdue_orders, key=lambda o: -o.dental_amount_overdue)[:8]
        upcoming_invoices = Order.search(active_dom + [('next_invoice_date', '!=', False)],
                                         order='next_invoice_date asc', limit=8)

        def ids_domain(records):
            return [('id', 'in', records.ids)]

        return {
            'company': {'id': company.id, 'name': company.name},
            'currency': {'symbol': currency.symbol, 'position': currency.position,
                         'digits': currency.decimal_places},
            'kpis': {
                'active': {'value': len(active), 'domain': active_dom},
                'members': {'value': len(active.dental_member_ids), 'domain': active_dom},
                'mrr': {'value': mrr, 'domain': active_dom},
                'arr': {'value': mrr * 12, 'domain': active_dom},
                'new_month': {'value': len(Order.search(new_dom)), 'domain': new_dom},
                'renewed_month': {'value': Order.search_count(renewed_dom), 'domain': renewed_dom},
                'churn_month': {'value': Order.search_count(churn_dom), 'domain': churn_dom},
                'paused': {'value': Order.search_count(confirmed + [('subscription_state', '=', '4_paused')]),
                           'domain': confirmed + [('subscription_state', '=', '4_paused')]},
                'to_renew': {'value': Order.search_count(confirmed + [('subscription_state', '=', '5_renew')]),
                             'domain': confirmed + [('subscription_state', '=', '5_renew')]},
                'expiring_30': {'value': Order.search_count(expiring_dom), 'domain': expiring_dom},
                'overdue_subs': {'value': len(overdue_orders), 'domain': ids_domain(overdue_orders)},
                'suspended': {'value': len(suspended), 'domain': ids_domain(suspended)},
                'overdue_amount': {'value': sum(overdue_invoices.mapped('amount_residual_signed')),
                                   'count': len(overdue_invoices), 'domain': overdue_inv_dom},
                'draft_invoices': {'value': Move.search_count(draft_inv_dom), 'domain': draft_inv_dom},
                'invoiced_month': {'value': sum(month_invoices.mapped('amount_total_signed')),
                                   'domain': month_inv_dom},
                'collected_month': {'value': collected},
                'benefit_uses': {'value': len(usage_lines), 'domain': usage_dom},
                'benefit_value': {'value': benefit_value, 'domain': usage_dom},
            },
            'by_type': by_type,
            'trend': trend,
            'expiring': [order_row(o) for o in expiring],
            'overdue': [order_row(o) for o in overdue_rows],
            'upcoming_invoices': [order_row(o) for o in upcoming_invoices],
            'generated_at': fields.Datetime.to_string(fields.Datetime.now()),
        }
