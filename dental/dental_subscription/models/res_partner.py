from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    dental_subscription_ids = fields.Many2many(
        'sale.order', 'sale_order_dental_member_rel', 'partner_id', 'order_id',
        string='Dental Memberships', readonly=True, copy=False)
    dental_membership_count = fields.Integer(
        string='Memberships', compute='_compute_dental_membership', compute_sudo=True)
    dental_membership_summary = fields.Char(
        string='Membership', compute='_compute_dental_membership', compute_sudo=True,
        help='Running memberships and packages of this patient in the selected branches.')
    has_active_dental_membership = fields.Boolean(
        string='Active Membership', compute='_compute_dental_membership', compute_sudo=True)

    def _dental_running_subscriptions(self):
        """Running dental subscriptions covering this patient, limited to the branches selected
        in the company switcher (computed with sudo, so filter explicitly)."""
        self.ensure_one()
        companies = self.env.companies
        return self.sudo().dental_subscription_ids.filtered(
            lambda o: o.state == 'sale' and not o.is_upsell and o.company_id in companies
            and o.subscription_state in ('3_progress', '4_paused', '5_renew'))

    def _compute_dental_membership(self):
        for partner in self:
            if not partner.id:
                partner.dental_membership_count = 0
                partner.dental_membership_summary = False
                partner.has_active_dental_membership = False
                continue
            running = partner._dental_running_subscriptions()
            partner.dental_membership_count = len(running)
            parts = []
            usable = False
            for order in running:
                ok, status = order._dental_benefits_usable_on(fields.Date.context_today(partner))
                usable = usable or ok
                product = order.order_line.product_id.filtered('dental_membership_type')[:1]
                parts.append('%s (%s)' % (product.name or order.name, status))
            partner.dental_membership_summary = ', '.join(parts) or False
            partner.has_active_dental_membership = usable

    def action_view_dental_memberships(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('dental_subscription.action_dental_subscriptions')
        action['domain'] = [('is_dental_subscription', '=', True), ('dental_member_ids', 'in', self.id)]
        action['context'] = {
            'default_is_subscription': True,
            'default_partner_id': self.id,
            'default_dental_member_ids': [self.id],
        }
        return action
