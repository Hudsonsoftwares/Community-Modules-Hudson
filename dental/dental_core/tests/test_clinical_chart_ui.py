from unittest.mock import patch

from odoo.tests import HttpCase, tagged
from odoo.tests.common import ChromeBrowser

_spawn_chrome = ChromeBrowser._spawn_chrome


def _spawn_chrome_without_webgl(self, cmd):
    # Software WebGL in a headless browser renders the 3D jaw far too slowly for a UI test;
    # without WebGL the widget uses its 2D tooth chart, which hosts the same tooth window.
    return _spawn_chrome(self, cmd[:-1] + ['--disable-webgl', '--disable-3d-apis'] + cmd[-1:])


@tagged('post_install', '-at_install', 'dental_clinical_chart_ui')
class TestClinicalChartUI(HttpCase):
    """Clinical Chart page of a consultation: the 3D odontogram comes first with the diagnosis
    list right under it (no examination blocks), a tooth opens in its own window that Escape
    closes, and typing a tooth number + Enter jumps straight to that tooth."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        patient = cls.env['res.partner'].create({
            'name': 'Chart Patient', 'is_dental_patient': True, 'phone': '9000000123',
            'date_of_birth': '1990-01-01',  # adult: permanent dentition (11-48)
        })
        cls.case = cls.env['dental.case'].create({'patient_id': patient.id, 'chief_complaint': 'Pain on 21'})
        # Record-finding controls are only enabled for dentists
        cls.env.ref('base.user_admin').write({'group_ids': [(4, cls.env.ref('dental_base.group_dental_dentist').id)]})

    def test_chart_page_tooth_window_and_search(self):
        code = """
            (async () => {
                const wait = (check, label) => new Promise((resolve, reject) => {
                    let tries = 0;
                    const timer = setInterval(() => {
                        let value = false;
                        try { value = check(); } catch (e) { value = false; }
                        if (value) { clearInterval(timer); resolve(value); }
                        else if (++tries > 200) { clearInterval(timer); reject(new Error('Timeout: ' + label)); }
                    }, 100);
                });
                const $ = (sel) => document.querySelector(sel);
                const key = (k, target = document.body) =>
                    target.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }));
                const badge = () => $('.o_dx_tooth_modal .dx-modal-head .dx-tooth-badge')?.textContent.trim();

                const tab = await wait(() => [...document.querySelectorAll('.o_notebook .nav-link')]
                    .find((a) => a.textContent.trim() === 'Clinical Chart'), 'Clinical Chart tab');
                tab.click();
                const odontogram = await wait(() => $('.o_dental_odontogram_wrapper'), 'odontogram');
                const page = odontogram.closest('.tab-pane') || document;
                const text = page.textContent;
                if (text.includes("Today's Examination") || text.includes('Examinations of this Case')) {
                    throw new Error('Examination sections must be removed from the Clinical Chart');
                }
                const diagnosisTitle = await wait(() => page.querySelector('.o_dental_diagnosis_title'), 'diagnosis title');
                if (!(odontogram.compareDocumentPosition(diagnosisTitle) & Node.DOCUMENT_POSITION_FOLLOWING)) {
                    throw new Error('Diagnosis must come after the odontogram');
                }

                // Type "2", then "1", Enter: the tooth 21 window opens
                key('2');
                const input = await wait(() => $('.o_dx_tooth_search input'), 'search palette');
                if (input.value !== '2') { throw new Error('Palette should start with the typed digit, got ' + input.value); }
                const rows = () => [...document.querySelectorAll('.o_dx_tooth_search .dx-search-row .dx-search-num')].map((n) => n.textContent.trim());
                await wait(() => rows().length && rows().every((n) => n.startsWith('2')), 'only teeth 2x listed')
                    .catch(() => {
                        const chips = [...odontogram.querySelectorAll('.tooth-chip .chip-num-label')].map((n) => n.textContent.trim());
                        input.value = '';
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        return new Promise((r) => setTimeout(r, 300)).then(() => {
                            throw new Error('Unexpected rows: ' + rows().join(',') + ' | chips: ' + chips.join(',') + ' | hint: ' + ($('.o_dx_tooth_search .dx-search-hint')?.textContent || ''));
                        });
                    });
                input.value = '2a1';
                input.dispatchEvent(new Event('input', { bubbles: true }));
                if (input.value !== '21') { throw new Error('Search must keep digits only, got ' + input.value); }
                key('Enter', input);
                await wait(() => !$('.o_dx_tooth_search') && badge() === '21', 'tooth 21 window');
                if (!$('.o_dx_tooth_modal .dx-panel') || !$('.o_dx_tooth_modal .dx-stage svg')) {
                    throw new Error('Tooth window must show the tooth views and the finding panel');
                }

                // Everything fits in the window at 1366x768: no column scrolls, the tooth is compact
                const pause = (ms) => new Promise((r) => setTimeout(r, ms));
                const assertFits = (state) => {
                    const bad = ['.dx-modal-window', '.dx-modal-body', '.dx-stage', '.dx-panel-record', '.dx-panel-exam']
                        .map((sel) => [sel, $('.o_dx_tooth_modal ' + sel)])
                        .filter(([, el]) => !el || el.scrollHeight > el.clientHeight + 2)
                        .map(([sel, el]) => sel + (el ? ' ' + el.scrollHeight + '>' + el.clientHeight : ' missing'));
                    if (bad.length) { throw new Error('Tooth window scrolls (' + state + ') at ' + innerWidth + 'x' + innerHeight + ': ' + bad.join(', ')); }
                };
                await pause(400);
                assertFits('default');
                const colX = (sel) => $('.o_dx_tooth_modal ' + sel).getBoundingClientRect().left;
                if (!(colX('.dx-panel-record') < colX('.dx-stage') && colX('.dx-stage') < colX('.dx-panel-exam'))) {
                    throw new Error('Columns must read: Record finding | Tooth | Examination');
                }
                // The window wraps its content: the fullest column leaves no empty band at the bottom
                const slack = Math.min(...['.dx-panel-record', '.dx-stage', '.dx-panel-exam'].map((sel) => {
                    const col = $('.o_dx_tooth_modal ' + sel);
                    const last = [...col.children].filter((c) => c.getClientRects().length).pop();
                    const pad = parseFloat(getComputedStyle(col).paddingBottom);
                    return col.getBoundingClientRect().bottom - pad - last.getBoundingClientRect().bottom;
                }));
                if (slack > 6) { throw new Error('Empty space under every column: ' + Math.round(slack) + 'px'); }
                if (window.DENTAL_SNAPSHOT) { throw new Error('SNAPSHOT'); }
                const sideWidth = $('.o_dx_tooth_modal .dx-view-side').getBoundingClientRect().width;
                if (sideWidth > 70) { throw new Error('Tooth drawing too large: ' + sideWidth + 'px'); }
                if ($('.o_dx_tooth_modal .dx-rail')) { throw new Error('The tall number rail must be replaced by the arch picker'); }
                if (document.querySelectorAll('.o_dx_tooth_modal .dx-arch-picker .dx-rail-btn').length !== 32) {
                    throw new Error('Arch picker must list the 32 permanent teeth');
                }
                const tile = (label) => [...document.querySelectorAll('.o_dx_tooth_modal .dx-tile')].find((b) => b.textContent.trim() === label);
                tile('Pathology').click();
                await pause(300);
                assertFits('pathology');
                tile('Restoration').click();
                await pause(300);
                const chips = [...document.querySelectorAll('.o_dx_tooth_modal .dx-panel-record .dx-chip')];
                (chips.find((c) => c.textContent.trim() === 'Crown') || chips[0]).click();
                await pause(300);
                assertFits('restoration with materials');

                // Arrow keys step through the teeth, Escape closes the window
                key('ArrowRight');
                await wait(() => badge() === '22', 'next tooth');
                key('Escape');
                await wait(() => !$('.o_dx_tooth_modal'), 'window closed by Escape');
                if (!$('.o_form_view .o_notebook')) { throw new Error('Escape must not leave the form'); }

                // Clicking a tooth on the tooth-by-tooth chart opens the same window
                [...odontogram.querySelectorAll('.btn-view-mode')].find((b) => b.textContent.includes('Tooth-by-Tooth')).click();
                const col = await wait(() => odontogram.querySelector('.dx-arch-grid .dx-col'), 'chart teeth');
                col.click();
                await wait(() => badge(), 'window from chart click');
                $('.o_dx_tooth_modal .dx-modal-close').click();
                await wait(() => !$('.o_dx_tooth_modal'), 'window closed by button');
                // The tiles clicked above mark the case as edited: discard before leaving
                const discard = $('.o_form_button_cancel');
                if (discard) {
                    discard.click();
                    await wait(() => !$('.o_form_button_cancel') || !$('.o_form_status_indicator_buttons:not(.invisible)'), 'changes discarded');
                }
                console.log('test successful');
            })().catch((e) => console.error(e.message));
        """
        with patch.object(ChromeBrowser, '_spawn_chrome', _spawn_chrome_without_webgl):
            self.browser_js(f'/odoo/action-dental_core.action_dental_case/{self.case.id}', code, login='admin', timeout=180)
