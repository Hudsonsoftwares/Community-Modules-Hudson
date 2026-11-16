from odoo import fields
from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'dental_subscription')
class TestDentalSubscriptionDashboardUI(HttpCase):

    def test_dashboard_renders_live_figures(self):
        new_test_user(self.env, login='dash_manager', groups='base.group_user,dental_base.group_dental_admin',
                      company_id=self.env.company.id, company_ids=[self.env.company.id])
        patient = self.env['res.partner'].create({'name': 'Dashboard Member', 'is_dental_patient': True})
        order = self.env['sale.order'].create({
            'partner_id': patient.id,
            'is_subscription': True,
            'plan_id': self.env.ref('hudson_subscriptions.subscription_plan_monthly').id,
            'start_date': fields.Date.today(),
            'dental_member_ids': [(6, 0, patient.ids)],
            'order_line': [(0, 0, {
                'product_id': self.env.ref('dental_subscription.product_membership_individual').product_variant_id.id})],
        })
        order.action_confirm()
        expected = self.env['sale.order'].get_dental_subscription_dashboard()['kpis']['active']['value']
        self.assertGreaterEqual(expected, 1)
        action = self.env.ref('dental_subscription.action_dental_subscription_dashboard')
        code = """
            const tiles = document.querySelectorAll('.o_dental_sub_dashboard .dsd-tile');
            const active = tiles[0] && tiles[0].querySelector('.dsd-tile-value').textContent.trim();
            const bars = document.querySelectorAll('.o_dental_sub_dashboard .dsd-hbar-row').length;
            if (tiles.length === 8 && active === '%s' && bars === 5) {
                console.log('test successful');
            } else {
                console.error('Dashboard not rendered as expected: tiles=' + tiles.length + ' active=' + active + ' bars=' + bars);
            }
        """ % expected
        self.browser_js(f'/odoo/action-{action.id}', code, ready="!!document.querySelector('.dsd-tile')", login='dash_manager')
