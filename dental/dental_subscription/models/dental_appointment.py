from odoo import fields, models


class DentalAppointment(models.Model):
    _inherit = 'dental.appointment'

    # Shown to reception and doctors: what the patient's membership covers before the visit is billed.
    # Summaries only (compute_sudo, filtered on the appointment's branch); no access to the contracts.
    dental_membership_summary = fields.Char(
        string='Membership', compute='_compute_dental_membership', compute_sudo=True)
    has_active_dental_membership = fields.Boolean(
        string='Active Membership', compute='_compute_dental_membership', compute_sudo=True)
    dental_membership_benefits = fields.Text(
        string='Membership Benefits', compute='_compute_dental_membership', compute_sudo=True)

    def _compute_dental_membership(self):
        today = fields.Date.context_today(self)
        for appt in self:
            branch = appt.branch_id or appt.company_id
            orders = appt.patient_id.sudo().dental_subscription_ids.filtered(
                lambda o: o.state == 'sale' and not o.is_upsell and o.company_id == branch
                and o.subscription_state in ('3_progress', '4_paused', '5_renew'))
            summary, lines, active = [], [], False
            for order in orders:
                ok, status = order._dental_benefits_usable_on(today)
                active = active or ok
                product = order.order_line.product_id.filtered('dental_membership_type')[:1]
                summary.append('%s – %s' % (product.name or order.name, status))
                if ok:
                    for benefit in order.dental_benefit_ids:
                        left = '∞' if benefit.is_unlimited else '%g' % benefit.remaining_qty
                        lines.append('• %s (%s left)' % (benefit.name, left))
            appt.dental_membership_summary = ', '.join(summary) or False
            appt.has_active_dental_membership = active
            appt.dental_membership_benefits = '\n'.join(lines) or False
