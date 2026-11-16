# -*- coding: utf-8 -*-
import re
from datetime import timedelta

from odoo.tests import HttpCase, tagged

from .common import TeleconsultCommonMixin


@tagged('post_install', '-at_install', 'dental_teleconsult')
class TestTeleconsultHttp(TeleconsultCommonMixin, HttpCase):
    """Patient journey through the public waiting room (guest link and portal login)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_teleconsult_clinic()

    def _path(self, appt, suffix=''):
        return '/dental/teleconsult/%s%s' % (appt.teleconsult_access_token, suffix)

    def _csrf(self, html):
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertTrue(match, "The page must contain a form with a CSRF token")
        return match.group(1)

    def test_unknown_token_is_404(self):
        self.assertEqual(self.url_open('/dental/teleconsult/%s' % ('x' * 43)).status_code, 404)
        self.assertEqual(self.url_open('/dental/teleconsult/short').status_code, 404)

    def test_guest_journey(self):
        appt = self._online_appointment()
        # 1. Identity check first: nothing about payment or the room is shown yet
        page = self.url_open(self._path(appt))
        self.assertEqual(page.status_code, 200)
        self.assertIn('Confirm your identity', page.text)
        self.assertNotIn('Payment required', page.text)
        self.assertEqual(page.headers.get('X-Robots-Tag'), 'noindex, nofollow')

        wrong = self.url_open(self._path(appt, '/verify'),
                              data={'csrf_token': self._csrf(page.text), 'dob': '2001-01-01'})
        self.assertIn('do not match', wrong.text)
        appt.invalidate_recordset()
        self.assertEqual(appt.teleconsult_failed_verifications, 1)

        # 2. Correct date of birth -> payment required
        page = self.url_open(self._path(appt, '/verify'),
                             data={'csrf_token': self._csrf(wrong.text), 'dob': '1990-05-17'})
        self.assertIn('Payment required', page.text)
        self.assertIn('Pay now', page.text)
        self.assertEqual(self.url_open(self._path(appt, '/status')).json()['stage'], 'payment')

        # 3. Paid -> ready; terms must be accepted
        self._pay(appt.teleconsult_invoice_id)
        page = self.url_open(self._path(appt))
        self.assertIn('Enter the waiting room', page.text)
        no_terms = self.url_open(self._path(appt, '/ready'), data={'csrf_token': self._csrf(page.text)})
        self.assertIn('accept the online consultation terms', no_terms.text)

        # 4. Enter the waiting room: guest cookie set, doctor alerted
        page = self.url_open(self._path(appt, '/ready'),
                             data={'csrf_token': self._csrf(no_terms.text), 'accept_terms': 'on'})
        self.assertIn('You are in the waiting room', page.text)
        self.assertTrue(self.opener.cookies.get('dgid'), "The patient gets a Discuss guest identity")
        appt.invalidate_recordset()
        self.assertEqual(appt.teleconsult_state, 'waiting')
        self.assertTrue(appt.teleconsult_guest_id)
        self.assertEqual(self.url_open(self._path(appt, '/status')).json()['stage'], 'waiting')
        # Not admitted yet: the room redirects back to the lobby
        room = self.url_open(self._path(appt, '/room'), allow_redirects=False)
        self.assertNotIn('/discuss/channel/', room.headers.get('Location', ''))

        # 5. Doctor admits -> status points to the room -> room opens the Discuss video page
        appt.with_user(self.dentist_user).action_teleconsult_admit()
        status = self.url_open(self._path(appt, '/status')).json()
        self.assertEqual(status['stage'], 'in_call')
        room = self.url_open(status['room_url'], allow_redirects=False)
        self.assertIn('/discuss/channel/%s' % appt.teleconsult_channel_id.id, room.headers['Location'])
        discuss_page = self.url_open('/discuss/channel/%s' % appt.teleconsult_channel_id.id)
        self.assertEqual(discuss_page.status_code, 200)

        # 6. Doctor ends -> link shows the consultation as ended, room no longer reachable
        appt.with_user(self.dentist_user).action_teleconsult_end()
        self.assertIn('Your consultation has ended', self.url_open(self._path(appt)).text)
        self.assertEqual(self.url_open('/discuss/channel/%s' % appt.teleconsult_channel_id.id).status_code, 404)

    def test_verification_lock(self):
        appt = self._online_appointment()
        appt.teleconsult_failed_verifications = 5
        self.assertIn('locked', self.url_open(self._path(appt)).text)

    def test_room_not_open_yet(self):
        appt = self._online_appointment(start_in=timedelta(days=2))
        appt.sudo().teleconsult_payment_waived = True
        page = self.url_open(self._path(appt))
        page = self.url_open(self._path(appt, '/verify'),
                             data={'csrf_token': self._csrf(page.text), 'dob': '1990-05-17'})
        self.assertIn('The waiting room opens at', page.text)
        self.assertNotIn('Enter the waiting room', page.text)

    def test_cancelled_link_closed(self):
        appt = self._online_appointment()
        appt.action_cancel()
        self.assertIn('no longer active', self.url_open(self._path(appt)).text)

    def _verified_page(self, appt):
        page = self.url_open(self._path(appt))
        return self.url_open(self._path(appt, '/verify'),
                             data={'csrf_token': self._csrf(page.text), 'dob': '1990-05-17'})

    def test_share_files_from_waiting_room(self):
        appt = self._online_appointment()
        appt.sudo().teleconsult_payment_waived = True
        page = self._verified_page(appt)
        self.assertIn('Share with your dentist', page.text)
        png = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
        response = self.url_open(
            self._path(appt, '/share'),
            data={'csrf_token': self._csrf(page.text), 'patient_notes': 'Swelling near molar'},
            files=[('files', ('swelling.png', png, 'image/png')),
                   ('files', ('notes.exe', b'MZ\x90\x00binary', 'application/octet-stream'))])
        self.assertIn('Some files were not accepted', response.text)
        appt.invalidate_recordset()
        self.assertEqual(appt.teleconsult_upload_ids.mapped('name'), ['swelling.png'])
        self.assertEqual(appt.teleconsult_patient_notes, 'Swelling near molar')
        self.assertIn('swelling.png', self.url_open(self._path(appt)).text)

    def test_visit_summary_page_requires_identity(self):
        appt = self._online_appointment()
        self._run_session(appt)
        # Ended, no summary yet: generic message, no identity needed
        self.assertIn('Your consultation has ended', self.url_open(self._path(appt)).text)
        rx = self._issued_prescription(appt)
        appt.write({'teleconsult_outcome': 'in_clinic',
                    'teleconsult_summary': '<p>Cracked tooth suspected, X-ray needed.</p>'})
        appt.with_user(self.dentist_user).action_teleconsult_send_summary()

        page = self.url_open(self._path(appt))
        self.assertIn('Confirm your identity', page.text)
        self.assertNotIn('Cracked tooth', page.text)
        self.assertEqual(self.url_open(self._path(appt, '/prescription/%s' % rx.id)).status_code, 404)

        page = self.url_open(self._path(appt, '/verify'),
                             data={'csrf_token': self._csrf(page.text), 'dob': '1990-05-17'})
        self.assertIn('Your visit summary', page.text)
        self.assertIn('Cracked tooth suspected', page.text)
        self.assertIn('recommends an in-person visit', page.text)
        download = self.url_open(self._path(appt, '/prescription/%s' % rx.id))
        self.assertEqual(download.status_code, 200)
        self.assertIn('attachment', download.headers.get('Content-Disposition', ''))
        other_rx = self._issued_prescription(self._online_appointment(start_in=timedelta(days=3)))
        self.assertEqual(self.url_open(self._path(appt, '/prescription/%s' % other_rx.id)).status_code, 404)

    def test_portal_patient(self):
        self.env['res.users'].create({
            'name': 'TC Patient', 'login': 'tc_patient_web', 'password': 'tc_patient_web_pwd',
            'partner_id': self.patient.id, 'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        appt = self._online_appointment()
        appt.sudo().teleconsult_payment_waived = True
        self.authenticate('tc_patient_web', 'tc_patient_web_pwd')
        listing = self.url_open('/my/teleconsultations')
        self.assertEqual(listing.status_code, 200)
        self.assertIn(appt.name, listing.text)
        self.assertIn(self._path(appt), listing.text)
        # Logged in as the patient: no identity question
        page = self.url_open(self._path(appt))
        self.assertIn('Enter the waiting room', page.text)
        self.url_open(self._path(appt, '/ready'), data={'csrf_token': self._csrf(page.text), 'accept_terms': 'on'})
        appt.invalidate_recordset()
        self.assertEqual(appt.teleconsult_partner_id, self.patient)
        self.assertFalse(appt.teleconsult_guest_id)
