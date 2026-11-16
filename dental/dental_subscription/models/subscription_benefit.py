from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models

PERIOD_DELTA = {
    'days': lambda n: relativedelta(days=n),
    'weeks': lambda n: relativedelta(weeks=n),
    'months': lambda n: relativedelta(months=n),
    'years': lambda n: relativedelta(years=n),
}


def _window_containing(start, on_date, step):
    """[from, to) window of ``step`` periods counted from ``start`` that contains ``on_date``.

    ``step(k)`` returns the relativedelta of k periods; computing start + k periods (instead of
    adding one period repeatedly) avoids month-end drift.
    """
    if on_date < start:
        return start, start + step(1)
    # Jump close to the target using the average period length, then adjust exactly
    period_days = max((start + step(1) - start).days, 1)
    k = max((on_date - start).days // period_days - 1, 0)
    while k > 0 and start + step(k) > on_date:
        k -= 1
    while start + step(k + 1) <= on_date:
        k += 1
    return start + step(k), start + step(k + 1)


class DentalSubscriptionBenefit(models.Model):
    """Benefit entitlement of one subscription.

    Usage is not stored separately: it *is* the invoice lines that applied the benefit
    (``account.move.line.dental_subscription_benefit_id``). Cancelling an invoice therefore
    gives the benefit back, and usage can never drift from billing.
    """
    _name = 'dental.subscription.benefit'
    _inherit = ['dental.benefit.mixin']
    _description = 'Subscription Benefit Entitlement'
    _order = 'order_id, sequence, id'
    _check_company_auto = True

    order_id = fields.Many2one(
        'sale.order', string='Subscription', required=True, ondelete='cascade', index=True,
        domain=[('is_dental_subscription', '=', True)])
    company_id = fields.Many2one(related='order_id.company_id', store=True, index=True, string='Branch')
    rule_id = fields.Many2one('dental.membership.benefit.rule', string='Source Rule', ondelete='set null', readonly=True)
    treatment_plan_id = fields.Many2one(
        'dental.treatment.plan', string='Treatment Plan', check_company=True, index='btree_not_null',
        help='Restricts the benefit to sessions of this treatment plan (orthodontic installments).')
    partner_id = fields.Many2one(related='order_id.partner_id', string='Subscriber')
    subscription_state = fields.Selection(related='order_id.subscription_state')

    usage_line_ids = fields.One2many(
        'account.move.line', 'dental_subscription_benefit_id', string='Usage', readonly=True)
    used_qty = fields.Float(string='Used (current period)', compute='_compute_usage', compute_sudo=True)
    remaining_qty = fields.Float(string='Remaining', compute='_compute_usage', compute_sudo=True)
    total_used_qty = fields.Float(string='Used (all time)', compute='_compute_usage', compute_sudo=True)
    period_label = fields.Char(string='Current Period', compute='_compute_usage', compute_sudo=True)
    is_unlimited = fields.Boolean(compute='_compute_usage', compute_sudo=True)

    @api.depends('usage_line_ids.quantity', 'usage_line_ids.parent_state', 'quantity_limit', 'limit_period',
                 'order_id.start_date', 'order_id.end_date', 'order_id.plan_id')
    def _compute_usage(self):
        today = fields.Date.context_today(self)
        for benefit in self:
            date_from, date_to = benefit._get_window(today)
            benefit.total_used_qty = sum(benefit._active_usage_lines().mapped('quantity'))
            benefit.used_qty = benefit._used_qty_between(date_from, date_to)
            benefit.is_unlimited = not benefit.quantity_limit
            benefit.remaining_qty = 0.0 if benefit.is_unlimited else max(benefit.quantity_limit - benefit.used_qty, 0.0)
            if date_from and date_to:
                benefit.period_label = '%s → %s' % (date_from, date_to - relativedelta(days=1))
            elif date_from:
                benefit.period_label = _('From %s', date_from)
            else:
                benefit.period_label = False

    # ------------------------------------------------------------------
    # Usage helpers (also used while billing)
    # ------------------------------------------------------------------
    def _active_usage_lines(self):
        return self.sudo().usage_line_ids.filtered(
            lambda l: l.move_id.state != 'cancel' and l.move_id.move_type == 'out_invoice')

    @staticmethod
    def _line_date(line):
        move = line.move_id
        return move.invoice_date or move.date or fields.Date.to_date(move.create_date)

    def _get_window(self, on_date):
        """(date_from, date_to) of the limit window containing ``on_date``; date_to is exclusive or False."""
        self.ensure_one()
        order = self.order_id
        start = order.start_date or on_date
        if self.limit_period == 'term':
            end = order.end_date and order.end_date + relativedelta(days=1)
            return start, end or False
        if self.limit_period == 'year':
            return _window_containing(start, on_date, lambda k: relativedelta(years=k))
        plan = order.plan_id
        if not plan or plan.billing_period_value <= 0:
            return start, False
        unit = PERIOD_DELTA.get(plan.billing_period_unit, PERIOD_DELTA['months'])
        value = plan.billing_period_value
        return _window_containing(start, on_date, lambda k: unit(k * value))

    def _used_qty_between(self, date_from, date_to):
        self.ensure_one()
        lines = self._active_usage_lines().filtered(
            lambda l: (not date_from or self._line_date(l) >= date_from)
            and (not date_to or self._line_date(l) < date_to))
        return sum(lines.mapped('quantity'))

    def _remaining_on(self, on_date, pending=0.0):
        """Uses left on ``on_date``; ``pending`` counts uses reserved earlier in the same billing batch."""
        self.ensure_one()
        if not self.quantity_limit:
            return float('inf')
        date_from, date_to = self._get_window(on_date)
        return self.quantity_limit - self._used_qty_between(date_from, date_to) - pending

    def _applies_to_line(self, template, session):
        self.ensure_one()
        if self.treatment_plan_id:
            # Installment coverage: only sessions of the financed plan, whatever the treatment
            return bool(session) and session.plan_id == self.treatment_plan_id
        return self._matches_product(template)

    def action_view_usage(self):
        self.ensure_one()
        return {
            'name': _('Benefit Usage – %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move.line',
            'view_mode': 'list',
            'views': [(self.env.ref('dental_subscription.view_benefit_usage_list').id, 'list')],
            'domain': [('dental_subscription_benefit_id', '=', self.id)],
            'context': {'create': False},
        }
