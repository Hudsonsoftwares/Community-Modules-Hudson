from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install', 'dental_dashboard_scroll')
class TestDentistDashboardScroll(HttpCase):
    """The Dentist Workspace dashboard is taller than the screen: it must scroll."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        admin = cls.env.ref('base.user_admin')
        admin.write({'group_ids': [(4, cls.env.ref('dental_base.group_dental_dentist').id)]})
        if not cls.env['hr.employee'].search([('user_id', '=', admin.id), ('dental_role', '=', 'dentist')]):
            cls.env['hr.employee'].create({'name': 'Dr. Scroll', 'dental_role': 'dentist', 'user_id': admin.id})

    def test_dashboard_scrolls(self):
        code = """
            (async () => {
                const wait = (check, label) => new Promise((resolve, reject) => {
                    let tries = 0;
                    const timer = setInterval(() => {
                        let value = false;
                        try { value = check(); } catch (e) { value = false; }
                        if (value) { clearInterval(timer); resolve(value); }
                        else if (++tries > 150) { clearInterval(timer); reject(new Error('Timeout: ' + label)); }
                    }, 100);
                });
                const view = await wait(() => document.querySelector('.o_dentist_dashboard_view .dd-container'), 'dashboard');
                await new Promise((r) => setTimeout(r, 1500));
                const content = view.getBoundingClientRect();
                if (content.bottom <= innerHeight) {
                    throw new Error('Test setup: dashboard fits the screen (' + Math.round(content.bottom) + ' <= ' + innerHeight + ')');
                }
                // Something between the dashboard and the page must scroll it into view
                const chain = [];
                let scroller = null;
                for (let el = view; el; el = el.parentElement) {
                    const st = getComputedStyle(el);
                    chain.push(`${el.tagName}.${[...el.classList].slice(0, 3).join('.')} h=${el.clientHeight}/${el.scrollHeight} oy=${st.overflowY}`);
                    if (!scroller && ['auto', 'scroll'].includes(st.overflowY) && el.scrollHeight > el.clientHeight + 5) {
                        scroller = el;
                    }
                }
                if (!scroller) { throw new Error('No scroll container: ' + chain.join(' | ')); }
                scroller.scrollTop = 400;
                await new Promise((r) => setTimeout(r, 200));
                if (scroller.scrollTop < 50) { throw new Error('Scroll container does not move: ' + chain.join(' | ')); }
                console.log('test successful');
            })().catch((e) => console.error(e.message));
        """
        self.browser_js('/odoo/action-dental_core.action_dentist_professional_dashboard', code, login='admin', timeout=120)
