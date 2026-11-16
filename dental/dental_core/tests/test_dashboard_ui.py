from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install', 'dental_dashboard_ui')
class TestAdminDashboardUI(HttpCase):
    """The Dental Clinic dashboard renders the selected clinic's name and its configurable floor plan,
    and an administrator can lay out rooms and live elements and save them."""

    def test_floor_plan_edit_and_save(self):
        company = self.env.ref('base.main_company')
        self.env['dental.floor.room'].search([('company_id', '=', company.id)]).unlink()
        self.env['dental.floor.element'].search([('company_id', '=', company.id)]).unlink()
        code = """
            (async () => {
                const wait = (check, label) => new Promise((resolve, reject) => {
                    let tries = 0;
                    const timer = setInterval(() => {
                        const value = check();
                        if (value) { clearInterval(timer); resolve(value); }
                        else if (++tries > 150) { clearInterval(timer); reject(new Error('Timeout: ' + label)); }
                    }, 100);
                });
                const $ = (sel) => document.querySelector(sel);
                const buttonWithText = (text) => [...document.querySelectorAll('.dfp button')]
                    .find((b) => b.textContent.includes(text));

                await wait(() => $('.dfp-toolbar'), 'floor plan toolbar');
                const title = $('.title-heading').textContent.trim();
                if (title !== %(company)s) { throw new Error('Unexpected title: ' + title); }
                if ($('.right-branch-selector')) { throw new Error('Branch selector should be removed'); }

                (await wait(() => buttonWithText('Start from Standard Layout'), 'standard layout button')).click();
                await wait(() => document.querySelectorAll('.dfp-room').length && $('.dfp-panel'), 'rooms + edit panel');
                if (!document.querySelectorAll('.dfp-fixture svg path').length) { throw new Error('Equipment icons not rendered'); }
                const fixturesBefore = document.querySelectorAll('.dfp-fixture').length;
                (await wait(() => $('.dfp-fixture-item'), 'equipment palette')).click();
                await wait(() => document.querySelectorAll('.dfp-fixture').length === fixturesBefore + 1, 'equipment added');
                (await wait(() => $('.dfp-fx-rotate'), 'rotate handle'));
                [...document.querySelectorAll('.dfp-panel button')].find((b) => b.title.startsWith('Rotate right')).click();
                [...document.querySelectorAll('.dfp-tab')].find((b) => b.textContent.includes('Live Data')).click();
                const before = document.querySelectorAll('.dfp-element').length;
                (await wait(() => $('.dfp-palette-item'), 'palette')).click();
                await wait(() => document.querySelectorAll('.dfp-element').length === before + 1, 'element added');
                buttonWithText('Add Room').click();
                await wait(() => [...document.querySelectorAll('.dfp-room-name')].some((n) => n.textContent === 'New Room'), 'room added');
                buttonWithText('Save Layout').click();
                await wait(() => !$('.dfp-is-editing') && buttonWithText('Edit Layout'), 'saved');
                console.log('test successful');
            })().catch((e) => console.error(e.message));
        """ % {'company': repr(company.name)}
        self.browser_js('/odoo/action-dental_core.action_admin_professional_dashboard', code, login='admin', timeout=120)
        rooms = self.env['dental.floor.room'].search([('company_id', '=', company.id)])
        self.assertIn('New Room', rooms.mapped('name'))
        self.assertTrue(self.env['dental.floor.element'].search_count([('company_id', '=', company.id)]))
        fixtures = self.env['dental.floor.fixture'].search([('company_id', '=', company.id)])
        self.assertIn(90, fixtures.mapped('rotation'), "The added equipment was rotated and saved")
