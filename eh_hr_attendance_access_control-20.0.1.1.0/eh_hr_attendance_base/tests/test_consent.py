# -*- encoding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tools import BinaryBytes

from .common import EhHrTestCommon


class TestConsentLifecycle(EhHrTestCommon):

    def test_create_starts_pending(self):
        consent = self.Consent.create({
            'employee_id': self.employee_alice.id,
            'consent_type': 'face',
        })
        self.assertEqual(consent.state, 'pending')
        self.assertFalse(consent.granted_on)
        self.assertFalse(consent.withdrawn_on)

    def test_grant_sets_dates_and_state(self):
        consent = self.Consent.create({
            'employee_id': self.employee_alice.id,
            'consent_type': 'face',
        })
        consent.action_grant()
        self.assertEqual(consent.state, 'granted')
        self.assertTrue(consent.granted_on)
        self.assertTrue(consent.expires_on)
        self.assertGreater(consent.expires_on, consent.granted_on)

    def test_withdraw_after_grant(self):
        consent = self._grant_face_consent(self.employee_alice)
        consent.action_withdraw()
        self.assertEqual(consent.state, 'withdrawn')
        self.assertTrue(consent.withdrawn_on)
        self.assertGreaterEqual(consent.withdrawn_on, consent.granted_on)

    def test_withdraw_rejected_before_granted_date(self):
        consent = self._grant_face_consent(self.employee_alice)
        with self.assertRaises(ValidationError):
            consent.write({'withdrawn_on': consent.granted_on - timedelta(days=1)})

    def test_employee_face_consent_state_compute(self):
        self.assertEqual(self.employee_alice.eh_face_consent_state, 'not_set')
        self._grant_face_consent(self.employee_alice)
        self.employee_alice.invalidate_recordset(['eh_face_consent_state', 'eh_consent_ids'])
        self.assertEqual(self.employee_alice.eh_face_consent_state, 'granted')

    def test_retention_sweep_expires_past_due_grants(self):
        consent = self._grant_face_consent(self.employee_alice)
        consent.write({'expires_on': fields.Datetime.now() - timedelta(days=1)})
        self.Consent._cron_retention_sweep()
        consent.invalidate_recordset()
        self.assertEqual(consent.state, 'expired')

    def test_retention_sweep_deletes_old_withdrawn_rows(self):
        consent = self._grant_face_consent(self.employee_alice)
        consent.action_withdraw()
        # Flush pending ORM writes before the raw SQL update, otherwise
        # the next implicit flush overwrites our aged write_date.
        self.env.flush_all()
        # Retention horizon defaults to 24 months. Force-age the row.
        cutoff = fields.Datetime.now() - timedelta(days=365 * 3)
        self.env.cr.execute(
            "UPDATE eh_hr_consent SET write_date = %s WHERE id = %s",
            (cutoff, consent.id),
        )
        self.Consent.invalidate_model()
        self.Consent._cron_retention_sweep()
        self.assertFalse(self.Consent.browse(consent.id).exists())

    def test_evidence_binary_round_trip(self):
        """The evidence artefact is stored and read back byte for byte.

        Binary fields hand out a BinaryValue on Odoo 20 and are written with
        BinaryBytes, and an attachment created the Odoo 19 way would be
        silently empty, so the stored bytes are what is asserted here and not
        just the presence of the attachment.
        """
        payload = b'%PDF-1.4 signed consent form'
        consent = self._grant_face_consent(self.employee_alice)
        consent.write({
            'evidence': BinaryBytes(payload, filename='consent.pdf'),
            'evidence_filename': 'consent.pdf',
        })
        consent.invalidate_recordset(['evidence'])

        self.assertEqual(consent.evidence.content, payload)
        self.assertEqual(consent.evidence.size, len(payload))

        attachment = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'eh.hr.consent'),
            ('res_id', '=', consent.id),
            ('res_field', '=', 'evidence'),
        ])
        self.assertEqual(len(attachment), 1)
        self.assertEqual(attachment.raw.content, payload)

    def test_tracked_grant_reaches_the_chatter(self):
        """Field tracking still reaches the chatter on Odoo 20, where the
        tracking values are rendered into the message body. Tracking is
        generated in a precommit callback, so it is only observable once that
        callback has run.
        """
        consent = self.Consent.create({
            'employee_id': self.employee_alice.id,
            'consent_type': 'face',
        })
        self.env.cr.precommit.run()
        before = consent.message_ids

        consent.action_grant()
        self.env.cr.precommit.run()

        posted = consent.message_ids - before
        self.assertTrue(posted, 'granting a consent posted no chatter message')
        self.assertIn('Granted', str(posted[0].body))

    def test_face_consent_state_search_operators(self):
        """The search method answers the operators the Odoo 20 domain
        optimiser produces, not only the plain equality the UI sends.
        """
        self._grant_face_consent(self.employee_alice)
        both = [self.employee_alice.id, self.employee_bob.id]

        in_list = self.Employee.search([
            ('id', 'in', both),
            ('eh_face_consent_state', 'in', ['granted', 'pending']),
        ])
        self.assertEqual(in_list, self.employee_alice)

        not_granted = self.Employee.search([
            ('id', 'in', both),
            ('eh_face_consent_state', '!=', 'granted'),
        ])
        self.assertEqual(not_granted, self.employee_bob)

        not_in = self.Employee.search([
            ('id', 'in', both),
            ('eh_face_consent_state', 'not in', ['not_set']),
        ])
        self.assertEqual(not_in, self.employee_alice)

    def test_face_consent_state_search(self):
        # Alice gets face consent, Bob does not.
        self._grant_face_consent(self.employee_alice)
        granted = self.Employee.search([
            ('id', 'in', [self.employee_alice.id, self.employee_bob.id]),
            ('eh_face_consent_state', '=', 'granted'),
        ])
        self.assertEqual(granted, self.employee_alice)
        not_set = self.Employee.search([
            ('id', 'in', [self.employee_alice.id, self.employee_bob.id]),
            ('eh_face_consent_state', '=', 'not_set'),
        ])
        self.assertEqual(not_set, self.employee_bob)
