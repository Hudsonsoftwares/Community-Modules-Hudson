# -*- coding: utf-8 -*-
import logging
import re
import secrets
from datetime import timedelta

import pytz
from markupsafe import Markup

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import format_datetime, html2plaintext

PAID_STATES = ('paid', 'in_payment')
# Fields whose change can open, move or close the video room
TELECONSULT_SYNC_FIELDS = {'consultation_mode', 'state', 'doctor_id'}
# Failed identity checks before the join link is locked (staff must send a new link)
MAX_FAILED_VERIFICATIONS = 5
ACTIVE_ROOM_STATES = ('scheduled', 'waiting', 'in_call')
# Files a patient may share from the waiting room
_logger = logging.getLogger(__name__)

UPLOAD_MAX_FILES = 8
UPLOAD_MAX_BYTES = 10 * 1024 * 1024
UPLOAD_MIMETYPES = ('image/jpeg', 'image/png', 'image/webp', 'image/gif', 'application/pdf')
UPLOAD_MARKER = 'dental_teleconsult_patient_upload'
# ir.attachment.description markers of the documents this module produces (used to file them, see
# dental_teleconsult_dms)
CONSENT_MARKER = 'dental_teleconsult_consent'
SUMMARY_MARKER = 'dental_teleconsult_summary'
TRANSCRIPT_MARKER = 'dental_teleconsult_transcript'
PRESCRIPTION_MARKER = 'dental_teleconsult_prescription'
# Wording the patient accepts in the waiting room (kept identical in the consent record)
TELEMEDICINE_TERMS = (
    "I agree to receive this consultation by video. I understand that the dentist cannot physically "
    "examine me, may recommend an in-clinic visit, and that the video call is private to me and the "
    "clinical team.")
RECORDING_TERMS = "I allow the clinic to record this consultation for my medical record."


class DentalAppointment(models.Model):
    _inherit = 'dental.appointment'

    consultation_mode = fields.Selection([
        ('in_clinic', 'In Clinic'),
        ('online', 'Online Video'),
    ], string='Consultation Mode', default='in_clinic', required=True, tracking=True,
        help="Online Video: the visit is held over a secure Odoo Discuss video call.")

    teleconsult_channel_id = fields.Many2one(
        'discuss.channel', string='Video Room', readonly=True, copy=False, index='btree_not_null')
    teleconsult_access_token = fields.Char(
        string='Join Token', readonly=True, copy=False, index='btree_not_null')
    teleconsult_join_url = fields.Char(string='Patient Join Link', compute='_compute_teleconsult_join_url')
    teleconsult_start_display = fields.Char(
        string='Local Start Time', compute='_compute_teleconsult_start_display',
        help="Start time in the clinic's timezone, as shown to the patient.")
    teleconsult_state = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('waiting', 'Patient Waiting'),
        ('in_call', 'In Call'),
        ('ended', 'Ended'),
        ('closed', 'Closed'),
    ], string='Online Status', readonly=True, copy=False, tracking=True)

    # Pay before joining
    teleconsult_invoice_id = fields.Many2one(
        'account.move', string='Payment Request', readonly=True, copy=False)
    teleconsult_payment_waived = fields.Boolean(string='Fee Waived', readonly=True, copy=False, tracking=True)
    teleconsult_payment_state = fields.Selection([
        ('not_required', 'Not Required'),
        ('due', 'Payment Due'),
        ('paid', 'Paid'),
        ('waived', 'Waived'),
    ], string='Online Payment', compute='_compute_teleconsult_payment_state', compute_sudo=True)
    teleconsult_payment_url = fields.Char(
        string='Payment Link', compute='_compute_teleconsult_payment_state', compute_sudo=True)

    # Who joins and when
    teleconsult_guest_id = fields.Many2one('mail.guest', string='Joined as Guest', readonly=True, copy=False)
    teleconsult_partner_id = fields.Many2one(
        'res.partner', string='Joined via Portal', readonly=True, copy=False)
    teleconsult_waiting_since = fields.Datetime(string='In Waiting Room Since', readonly=True, copy=False)
    teleconsult_started_at = fields.Datetime(string='Call Started', readonly=True, copy=False)
    teleconsult_ended_at = fields.Datetime(string='Call Ended', readonly=True, copy=False)
    teleconsult_duration = fields.Float(
        string='Call Duration (Minutes)', compute='_compute_teleconsult_duration')
    teleconsult_consent_at = fields.Datetime(string='Telemedicine Consent Given', readonly=True, copy=False)
    teleconsult_recording_consent = fields.Boolean(string='Recording Consent', readonly=True, copy=False)
    teleconsult_failed_verifications = fields.Integer(
        string='Failed Identity Checks', readonly=True, copy=False)
    teleconsult_reminder_sent = fields.Boolean(readonly=True, copy=False)
    teleconsult_consent_ip = fields.Char(string='Consent IP Address', readonly=True, copy=False)
    teleconsult_consent_user_agent = fields.Char(string='Consent Browser', readonly=True, copy=False)
    teleconsult_consent_method = fields.Selection([
        ('portal', 'Patient portal login'),
        ('identity', 'Join link + identity check'),
        ('link', 'Join link'),
    ], string='Identified By', readonly=True, copy=False)
    teleconsult_consent_attachment_id = fields.Many2one(
        'ir.attachment', string='Consent Record', readonly=True, copy=False)

    # Reporting (stored)
    teleconsult_call_minutes = fields.Float(
        string='Call Minutes', compute='_compute_teleconsult_report_values', store=True, aggregator='avg')
    teleconsult_wait_minutes = fields.Float(
        string='Waiting Minutes', compute='_compute_teleconsult_report_values', store=True, aggregator='avg',
        help="Time between the patient entering the waiting room and being admitted.")
    teleconsult_fee_amount = fields.Float(
        string='Online Fee', compute='_compute_teleconsult_report_values', store=True, aggregator='sum')

    # Colleagues invited into the call (specialist, assistant, interpreter...)
    teleconsult_colleague_ids = fields.Many2many(
        'res.users', 'dental_appointment_teleconsult_colleague_rel', 'appointment_id', 'user_id',
        string='Invited Colleagues', readonly=True, copy=False)
    teleconsult_recording_count = fields.Integer(compute='_compute_teleconsult_recording_count')

    # Shared by the patient before the call
    teleconsult_patient_notes = fields.Text(
        string='Patient\'s Description', readonly=True, copy=False,
        help="What the patient wrote in the online waiting room about their problem.")
    teleconsult_upload_ids = fields.Many2many(
        'ir.attachment', 'dental_appointment_teleconsult_upload_rel', 'appointment_id', 'attachment_id',
        string='Patient Photos & Files', readonly=True, copy=False,
        help="Photos, X-rays or documents the patient shared from the online waiting room.")
    teleconsult_upload_count = fields.Integer(compute='_compute_teleconsult_upload_count')

    # Visit outcome shared with the patient
    teleconsult_outcome = fields.Selection([
        ('advice', 'Advice Given'),
        ('prescription', 'Prescription Issued'),
        ('in_clinic', 'In-Clinic Visit Needed'),
        ('referral', 'Referred to Specialist'),
        ('emergency', 'Urgent Care Advised'),
    ], string='Consultation Outcome', copy=False, tracking=True)
    teleconsult_summary = fields.Html(
        string='Advice for the Patient', copy=False,
        help="Patient-friendly summary and instructions. Shown to the patient after the call and emailed with the visit summary.")
    teleconsult_summary_sent_at = fields.Datetime(string='Summary Sent', readonly=True, copy=False)
    teleconsult_summary_attachment_id = fields.Many2one(
        'ir.attachment', string='Visit Summary PDF', readonly=True, copy=False)
    teleconsult_prescription_ids = fields.Many2many(
        'dental.prescription', string='Prescriptions', compute='_compute_teleconsult_prescription_ids')

    # ---------------------------------------------------------
    # Computes & constraints
    # ---------------------------------------------------------
    @api.depends('teleconsult_access_token')
    def _compute_teleconsult_join_url(self):
        for appt in self:
            appt.teleconsult_join_url = (
                f"{appt.get_base_url()}/dental/teleconsult/{appt.teleconsult_access_token}"
                if appt.teleconsult_access_token else False)

    @api.depends('date_start', 'doctor_id', 'branch_id')
    def _compute_teleconsult_start_display(self):
        for appt in self:
            appt.teleconsult_start_display = (
                f"{appt._teleconsult_local_start()} ({appt._teleconsult_tz_label()})" if appt.date_start else False)

    @api.depends('consultation_mode', 'teleconsult_payment_waived', 'teleconsult_invoice_id.payment_state',
                 'teleconsult_invoice_id.state', 'branch_id', 'state')
    def _compute_teleconsult_payment_state(self):
        for appt in self:
            appt.teleconsult_payment_url = False
            if appt.consultation_mode != 'online':
                appt.teleconsult_payment_state = False
                continue
            if appt.teleconsult_payment_waived:
                appt.teleconsult_payment_state = 'waived'
                continue
            if not appt._teleconsult_company().dental_teleconsult_require_prepayment:
                appt.teleconsult_payment_state = 'not_required'
                continue
            invoices = appt._teleconsult_fee_invoices()
            if invoices:
                paid = all(inv.state == 'posted' and inv.payment_state in PAID_STATES for inv in invoices)
                appt.teleconsult_payment_state = 'paid' if paid else 'due'
                unpaid = invoices.filtered(lambda m: m.state == 'posted' and m.payment_state not in PAID_STATES)[:1]
                if unpaid:
                    appt.teleconsult_payment_url = unpaid.get_base_url() + unpaid.get_portal_url()
            elif appt.id and appt._get_consultation_fee_line_vals():
                appt.teleconsult_payment_state = 'due'
            else:
                appt.teleconsult_payment_state = 'not_required'

    @api.depends('teleconsult_started_at', 'teleconsult_ended_at', 'teleconsult_waiting_since',
                 'teleconsult_invoice_id.amount_total', 'teleconsult_invoice_id.state')
    def _compute_teleconsult_report_values(self):
        for appt in self:
            start, end, waiting = appt.teleconsult_started_at, appt.teleconsult_ended_at, appt.teleconsult_waiting_since
            appt.teleconsult_call_minutes = max((end - start).total_seconds() / 60.0, 0.0) if start and end else 0.0
            appt.teleconsult_wait_minutes = max((start - waiting).total_seconds() / 60.0, 0.0)                 if start and waiting else 0.0
            invoice = appt.sudo().teleconsult_invoice_id
            appt.teleconsult_fee_amount = invoice.amount_total if invoice and invoice.state == 'posted' else 0.0

    def _compute_teleconsult_recording_count(self):
        for appt in self:
            appt.teleconsult_recording_count = len(appt._teleconsult_recordings())

    def _teleconsult_recordings(self):
        """Call histories of the video room that hold a recording."""
        self.ensure_one()
        channel = self.sudo().teleconsult_channel_id
        if not channel:
            return self.env['discuss.call.history']
        return self.env['discuss.call.history'].sudo().search([
            ('channel_id', '=', channel.id),
            ('artifact_ids', 'any', [('recording_upload_pending', '=', False)]),
        ]).filtered('has_recording')

    @api.depends('teleconsult_upload_ids')
    def _compute_teleconsult_upload_count(self):
        for appt in self:
            appt.teleconsult_upload_count = len(appt.teleconsult_upload_ids)

    def _compute_teleconsult_prescription_ids(self):
        for appt in self:
            appt.teleconsult_prescription_ids = appt._teleconsult_prescriptions()

    def _teleconsult_prescriptions(self):
        """Prescriptions issued for this visit (not drafts or cancelled ones)."""
        self.ensure_one()
        if not self.id:
            return self.env['dental.prescription']
        domain = [('appointment_id', '=', self.id)]
        case = self.sudo().case_id
        if case and self.teleconsult_started_at:
            domain = ['|', ('appointment_id', '=', self.id), '&', ('case_id', '=', case.id),
                      ('create_date', '>=', self.teleconsult_started_at)]
        return self.env['dental.prescription'].sudo().search(
            domain + [('state', 'not in', ('draft', 'cancelled'))], order='id')

    @api.depends('teleconsult_started_at', 'teleconsult_ended_at')
    def _compute_teleconsult_duration(self):
        now = fields.Datetime.now()
        for appt in self:
            if appt.teleconsult_started_at:
                end = appt.teleconsult_ended_at or now
                appt.teleconsult_duration = max((end - appt.teleconsult_started_at).total_seconds() / 60.0, 0.0)
            else:
                appt.teleconsult_duration = 0.0

    @api.constrains('consultation_mode', 'appointment_type_id', 'branch_id')
    def _check_teleconsult_allowed(self):
        for appt in self.filtered(lambda a: a.consultation_mode == 'online'):
            if appt.appointment_type_id and not appt.appointment_type_id.allow_online:
                raise ValidationError(_("Appointment type '%s' is not available as an online consultation.",
                                        appt.appointment_type_id.name))
            if not appt._teleconsult_company().dental_teleconsult_enabled:
                raise ValidationError(_("Online video consultations are disabled for %s.",
                                        appt._teleconsult_company().name))

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------
    def _teleconsult_company(self):
        self.ensure_one()
        return self.branch_id or self.company_id or self.env.company

    def _teleconsult_doctor_user(self):
        self.ensure_one()
        return self.doctor_id.sudo().user_id

    def _teleconsult_tz(self):
        self.ensure_one()
        return (self._teleconsult_doctor_user().tz or self._teleconsult_company().partner_id.tz
                or self.env.user.tz or 'UTC')

    def _teleconsult_format_dt(self, value, dt_format='medium'):
        self.ensure_one()
        return format_datetime(self.env, value, tz=self._teleconsult_tz(), dt_format=dt_format) if value else ''

    def _teleconsult_window(self):
        """(opens_at, closes_at) of the join link, naive UTC."""
        self.ensure_one()
        company = self._teleconsult_company()
        opens = self.date_start - timedelta(minutes=company.dental_teleconsult_join_before or 0)
        closes = (self.date_end or self.date_start) + timedelta(minutes=company.dental_teleconsult_join_after or 0)
        return opens, closes

    def _teleconsult_fee_invoices(self):
        """Customer invoices (not cancelled) that carry this visit's consultation fee."""
        self.ensure_one()
        moves = self.env['account.move.line'].sudo().search([
            ('dental_appointment_id', '=', self.id)]).move_id if self.id else self.env['account.move']
        moves |= self.sudo().teleconsult_invoice_id
        return moves.filtered(lambda m: m.move_type == 'out_invoice' and m.state != 'cancel')

    def _teleconsult_can_join(self):
        self.ensure_one()
        return self.teleconsult_payment_state in ('not_required', 'paid', 'waived')

    def _teleconsult_is_patient_user(self, user):
        """A logged-in portal user is the patient (or the patient's guardian contact)."""
        self.ensure_one()
        if not user or user._is_public():
            return False
        return user.partner_id in (self.patient_id | self.patient_id.parent_id)

    def _teleconsult_identity_method(self):
        """How a guest proves identity: 'dob', 'phone' or False (no check possible / disabled)."""
        self.ensure_one()
        if not self._teleconsult_company().dental_teleconsult_verify_identity:
            return False
        patient = self.patient_id.sudo()
        if patient.date_of_birth:
            return 'dob'
        if len(re.sub(r'\D', '', patient.phone or '')) >= 4:
            return 'phone'
        return False

    def _teleconsult_check_identity(self, dob=None, phone_digits=None):
        self.ensure_one()
        method = self._teleconsult_identity_method()
        patient = self.patient_id.sudo()
        if method == 'dob':
            try:
                return bool(dob) and fields.Date.to_date(dob) == patient.date_of_birth
            except ValueError:
                return False
        if method == 'phone':
            digits = re.sub(r'\D', '', phone_digits or '')
            return len(digits) == 4 and re.sub(r'\D', '', patient.phone)[-4:] == digits
        return True

    def _teleconsult_check_clinician(self):
        user = self.env.user
        if not (self.env.su or user.has_group('dental_base.group_dental_dentist')
                or user.has_group('dental_base.group_dental_assistant')
                or user.has_group('dental_base.group_dental_admin')):
            raise AccessError(_("Only the clinical team can enter online consultation rooms."))

    def _teleconsult_check_front_desk(self):
        user = self.env.user
        if not (self.env.su or user.has_group('dental_base.group_dental_receptionist')
                or user.has_group('dental_base.group_dental_dentist')
                or user.has_group('dental_base.group_dental_manager')
                or user.has_group('dental_base.group_dental_admin')):
            raise AccessError(_("You are not allowed to manage online consultation links."))

    def _teleconsult_patient_members(self):
        """Room members that are not clinic staff (guests and portal patients)."""
        self.ensure_one()
        channel = self.sudo().teleconsult_channel_id
        return channel.channel_member_ids.filtered(
            lambda m: m.guest_id or (m.partner_id and not m.partner_id.user_ids.filtered(lambda u: u._is_internal())
                                     and m.partner_id != self.env.ref('base.partner_root')))

    # ---------------------------------------------------------
    # Room lifecycle
    # ---------------------------------------------------------
    def _teleconsult_prepare(self):
        """Create the join token, the private video room and the payment request."""
        for appt in self.filtered(lambda a: a.consultation_mode == 'online'):
            vals = {}
            if not appt.teleconsult_access_token:
                vals['teleconsult_access_token'] = secrets.token_urlsafe(32)
            if appt.teleconsult_state in (False, 'closed'):
                vals['teleconsult_state'] = 'scheduled'
            if vals:
                appt.sudo().write(vals)
            appt._teleconsult_ensure_channel()
            appt._teleconsult_ensure_payment_request()

    def _teleconsult_ensure_channel(self):
        self.ensure_one()
        appt = self.sudo()
        channel = appt.teleconsult_channel_id
        if not channel:
            # Created as OdooBot so no front-desk user becomes a member of a PHI video room
            channel = self.env['discuss.channel'].with_user(SUPERUSER_ID).create({
                'name': _("Online Consultation %(ref)s - %(patient)s", ref=appt.name, patient=appt.patient_id.name),
                'channel_type': 'group',
                'default_display_mode': 'video_full_screen',
                'dental_channel_type': 'teleconsult',
                'is_confidential_phi': True,
                'company_id': False,
                'dental_appointment_id': appt.id,
                'dental_patient_id': appt.patient_id.id,
            }).sudo()
            appt.teleconsult_channel_id = channel
        doctor_partner = appt._teleconsult_doctor_user().partner_id
        if doctor_partner and doctor_partner not in channel.channel_member_ids.partner_id:
            channel._add_members(partners=doctor_partner, post_joined_message=False)
        return channel

    def _teleconsult_ensure_payment_request(self):
        """Post the consultation fee invoice the patient must pay before joining."""
        self.ensure_one()
        appt = self.sudo()
        if appt.teleconsult_payment_state != 'due' or appt._teleconsult_fee_invoices():
            return appt.teleconsult_invoice_id
        self.env.cr.execute("SELECT id FROM dental_appointment WHERE id = %s FOR UPDATE", (appt.id,))
        fee = appt._get_consultation_fee_line_vals()
        if not fee:
            return self.env['account.move']
        try:
            with self.env.cr.savepoint():
                invoice, _extended = self.env['account.move'].sudo()._dental_create_or_extend_invoice(
                    appt.patient_id, appt._teleconsult_company(), [fee], origin=appt.name)
                invoice.action_post()
        except UserError as err:
            appt.message_post(body=_(
                "The online consultation payment request could not be created: %s",
                err.args[0] if err.args else err))
            return self.env['account.move']
        appt.teleconsult_invoice_id = invoice
        appt.message_post(body=_("Online consultation payment request %(invoice)s posted (%(amount)s). "
                                 "The patient can join once it is paid.",
                                 invoice=invoice.name, amount=invoice.amount_total))
        return invoice

    def _teleconsult_send_invitation(self):
        template = self.env.ref('dental_teleconsult.mail_template_teleconsult_invitation', raise_if_not_found=False)
        for appt in self.filtered(lambda a: a.consultation_mode == 'online' and a.teleconsult_access_token):
            if not appt.patient_id.email:
                appt.message_post(body=_("Online consultation link not emailed: the patient has no email address. "
                                         "Share the join link from the Online Consultation tab."))
            elif template:
                template.sudo().send_mail(appt.id, force_send=False)
                appt.message_post(body=_("Online consultation invitation sent to %s.", appt.patient_id.email))
        self.filtered(lambda a: a.consultation_mode == 'online' and a.teleconsult_access_token
                      )._teleconsult_invitation_sent()

    def _teleconsult_invitation_sent(self):
        """Hook called once the patient was invited (confirmation or new link), e.g. to also send an SMS."""
        return True

    def _teleconsult_sync(self, old_doctors=None):
        old_doctors = old_doctors or {}
        for appt in self:
            room_active = appt.teleconsult_state in ACTIVE_ROOM_STATES
            if appt.consultation_mode == 'online' and appt.state in ('confirmed', 'checked_in', 'in_consultation'):
                first_time = not appt.teleconsult_access_token
                appt._teleconsult_prepare()
                old_doctor = old_doctors.get(appt.id)
                if old_doctor and old_doctor != appt.doctor_id:
                    old_partner = old_doctor.sudo().user_id.partner_id
                    appt.sudo().teleconsult_channel_id.channel_member_ids.filtered(
                        lambda m: old_partner and m.partner_id == old_partner).unlink()
                if first_time and not self.env.context.get('dental_teleconsult_confirming'):
                    appt._teleconsult_send_invitation()
            elif room_active and appt.state == 'completed':
                appt._teleconsult_end_session(final_state='ended')
            elif room_active and (appt.consultation_mode != 'online' or appt.state in ('cancelled', 'no_show', 'pending')):
                appt._teleconsult_end_session(final_state='closed')

    def _teleconsult_end_session(self, final_state='ended'):
        """Remove the patient from the room, archive the chat and close the link."""
        for appt in self:
            channel = appt.sudo().teleconsult_channel_id
            was_in_call = appt.teleconsult_state == 'in_call'
            appt._teleconsult_patient_members().sudo().unlink()
            appt._teleconsult_colleague_members().sudo().unlink()
            vals = {'teleconsult_state': final_state}
            if was_in_call:
                vals['teleconsult_ended_at'] = fields.Datetime.now()
            appt.sudo().write(vals)
            if channel and was_in_call:
                channel.with_user(SUPERUSER_ID).message_post(
                    body=_("The online consultation has ended."), message_type='comment',
                    subtype_xmlid='mail.mt_comment')
                appt._teleconsult_archive_transcript()
            if final_state == 'closed':
                unpaid = appt.sudo().teleconsult_invoice_id.filtered(
                    lambda m: m.state == 'posted' and m.payment_state not in PAID_STATES)
                if unpaid and appt.state in ('cancelled', 'no_show'):
                    appt.message_post(body=_("Payment request %s is still open: cancel it or issue a credit note "
                                             "in Invoicing if the fee should not be charged.", unpaid.name))

    def _teleconsult_archive_transcript(self):
        """Copy the chat of this consultation (and its attachments) to the appointment chatter."""
        self.ensure_one()
        channel = self.sudo().teleconsult_channel_id
        domain = [('model', '=', 'discuss.channel'), ('res_id', '=', channel.id),
                  ('message_type', '=', 'comment'), ('author_id', '!=', self.env.ref('base.partner_root').id)]
        if self.teleconsult_started_at:
            domain.append(('date', '>=', self.teleconsult_started_at))
        messages = self.env['mail.message'].sudo().search(domain, order='id asc')
        if not messages:
            return
        rows = []
        attachments = self.env['ir.attachment']
        for msg in messages:
            author = msg.author_id.name or msg.author_guest_id.name or _('Patient')
            rows.append(Markup("<li><b>%s</b> <small>%s</small>: %s</li>") % (
                author, self._teleconsult_format_dt(msg.date, 'short'), msg.body or ''))
            attachments |= msg.attachment_ids
        attachment_ids = [att.copy({'res_model': self._name, 'res_id': self.id}).id for att in attachments.sudo()]
        transcript = Markup(
            '<html><head><meta charset="utf-8"/><title>%(title)s</title></head><body>'
            '<h1>%(title)s</h1><p>%(ref)s - %(patient)s - Dr. %(doctor)s<br/>%(when)s</p><ul>%(rows)s</ul></body></html>'
        ) % {
            'title': _("Online consultation chat transcript"), 'ref': self.name, 'patient': self.patient_id.name,
            'doctor': self.doctor_id.name or '', 'when': self.teleconsult_start_display or '',
            'rows': Markup().join(rows),
        }
        attachment_ids.append(self.env['ir.attachment'].sudo().create({
            'name': _("Online Consultation Transcript - %s.html", self.name).replace('/', '-'),
            'raw': str(transcript).encode(),
            'mimetype': 'text/html',
            'res_model': self._name, 'res_id': self.id,
            'description': TRANSCRIPT_MARKER,
        }).id)
        self.sudo().message_post(
            body=Markup("<p><b>%s</b></p><ul>%s</ul>") % (_("Online consultation chat transcript"), Markup().join(rows)),
            attachment_ids=attachment_ids,
            subtype_xmlid='mail.mt_note')

    # ---------------------------------------------------------
    # Patient side (called from the public controller, sudo)
    # ---------------------------------------------------------
    def _teleconsult_register_failed_verification(self):
        self.ensure_one()
        count = self.teleconsult_failed_verifications + 1
        self.sudo().teleconsult_failed_verifications = count
        if count == MAX_FAILED_VERIFICATIONS:
            self.sudo().message_post(body=_(
                "Online consultation link locked after %s failed identity checks. "
                "Use 'Send New Join Link' once the patient's identity is confirmed.", count))

    def _teleconsult_patient_ready(self, guest=None, partner=None, recording_consent=False, consent_info=None):
        """The verified patient enters the waiting room: check in and alert the doctor.

        ``consent_info``: {'ip', 'user_agent'} of the browser accepting the terms (evidence kept in
        the consent record).
        """
        self.ensure_one()
        appt = self.sudo()
        vals = {
            'teleconsult_guest_id': guest.id if guest else False,
            'teleconsult_partner_id': partner.id if partner else False,
            'teleconsult_recording_consent': bool(recording_consent),
        }
        first_consent = not appt.teleconsult_consent_at
        if first_consent:
            consent_info = consent_info or {}
            vals.update({
                'teleconsult_consent_at': fields.Datetime.now(),
                'teleconsult_consent_ip': (consent_info.get('ip') or '')[:64] or False,
                'teleconsult_consent_user_agent': (consent_info.get('user_agent') or '')[:255] or False,
                'teleconsult_consent_method': 'portal' if partner else (
                    'identity' if appt._teleconsult_identity_method() else 'link'),
            })
        newly_waiting = appt.teleconsult_state == 'scheduled'
        if newly_waiting:
            vals.update(teleconsult_state='waiting', teleconsult_waiting_since=fields.Datetime.now())
        appt.write(vals)
        if first_consent:
            appt._teleconsult_create_consent_record()
        if appt.teleconsult_state == 'in_call':
            # Reconnecting patient: put the new persona straight back into the room
            appt._teleconsult_add_patient_member()
            return
        if appt.state == 'confirmed':
            # Self check-in runs as OdooBot: the patient has no reception rights and must not be
            # added to the doctor's front-desk coordination channel
            appt.with_user(SUPERUSER_ID).sudo().action_check_in()
        if newly_waiting:
            appt.message_post(body=_(
                "Patient entered the online waiting room (joined via %(how)s). Telemedicine consent accepted; "
                "recording consent: %(rec)s.",
                how=_('patient portal') if partner else _('guest link'),
                rec=_('yes') if recording_consent else _('no')))
            appt._teleconsult_notify_doctor()

    def _teleconsult_render_pdf(self, report_xmlid, filename, marker):
        """Render a report of this appointment into an attachment. Never blocks the workflow."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                report = self.env.ref(report_xmlid)
                pdf, _type = self.env['ir.actions.report'].sudo()._render_qweb_pdf(report.report_name, self.ids)
                return self.env['ir.attachment'].sudo().create({
                    'name': filename.replace('/', '-'),
                    'raw': pdf,
                    'mimetype': 'application/pdf',
                    'res_model': self._name, 'res_id': self.id,
                    'description': marker,
                })
        except Exception:  # noqa: BLE001
            _logger.exception("Online consultation: could not render %s for %s", report_xmlid, self.name)
            return self.env['ir.attachment']

    def _teleconsult_create_consent_record(self):
        """PDF evidence of the telemedicine consent (wording, time, identification, browser)."""
        self.ensure_one()
        attachment = self._teleconsult_render_pdf(
            'dental_teleconsult.action_report_teleconsult_consent',
            _("Telemedicine Consent - %s.pdf", self.name), CONSENT_MARKER)
        if attachment:
            self.sudo().teleconsult_consent_attachment_id = attachment
        return attachment

    def _teleconsult_consent_terms(self):
        return {'telemedicine': _(TELEMEDICINE_TERMS), 'recording': _(RECORDING_TERMS)}

    def _teleconsult_colleague_members(self):
        """Room members invited as colleagues (never the treating doctor)."""
        self.ensure_one()
        channel = self.sudo().teleconsult_channel_id
        doctor_partner = self._teleconsult_doctor_user().partner_id
        partners = self.sudo().teleconsult_colleague_ids.partner_id - doctor_partner
        return channel.channel_member_ids.filtered(lambda m: m.partner_id and m.partner_id in partners)

    def _teleconsult_invite_colleagues(self, users, note=None):
        """Add internal users (specialist, assistant, interpreter...) to the video room and alert them."""
        self.ensure_one()
        self._teleconsult_check_clinician()
        users = users.filtered(lambda u: u._is_internal() and u.active)
        if self.teleconsult_state not in ACTIVE_ROOM_STATES:
            raise UserError(_("Colleagues can only be invited while the online consultation is open."))
        if not users:
            raise UserError(_("Select at least one internal user to invite."))
        appt = self.sudo()
        channel = appt._teleconsult_ensure_channel()
        new_partners = users.partner_id - channel.channel_member_ids.partner_id
        if new_partners:
            channel._add_members(partners=new_partners, post_joined_message=False)
        appt.teleconsult_colleague_ids = [(4, u.id) for u in users]
        names = ', '.join(users.mapped('name'))
        channel.with_user(SUPERUSER_ID).message_post(
            body=Markup("<p>%s</p>") % _("%(by)s invited %(names)s to this consultation.",
                                         by=self.env.user.name, names=names),
            message_type='comment', subtype_xmlid='mail.mt_comment')
        for user in users:
            user._bus_send('simple_notification', {
                'type': 'info', 'sticky': True,
                'title': _("Online consultation"),
                'message': _("%(by)s invites you to the online consultation %(ref)s (%(patient)s). "
                             "Open it from Discuss.%(note)s", by=self.env.user.name, ref=appt.name,
                             patient=appt.patient_id.name, note=(" " + note) if note else ''),
            })
        appt.message_post(body=_("%(by)s invited %(names)s to the online consultation.",
                                 by=self.env.user.name, names=names))
        return True

    def action_teleconsult_invite(self):
        self.ensure_one()
        self._teleconsult_check_clinician()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Invite a Colleague"),
            'res_model': 'dental.teleconsult.invite',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_appointment_id': self.id},
        }

    def action_teleconsult_recordings(self):
        self.ensure_one()
        self._teleconsult_check_clinician()
        recordings = self._teleconsult_recordings()
        if not recordings:
            raise UserError(_("There is no recording of this consultation."))
        action = self.env['ir.actions.act_window']._for_xml_id('mail.discuss_call_history_action')
        action['domain'] = [('id', 'in', recordings.ids)]
        if len(recordings) == 1:
            action.update(res_id=recordings.id, view_mode='form',
                          views=[view for view in action['views'] if view[1] == 'form'])
        return action

    def action_teleconsult_consent_record(self):
        self.ensure_one()
        attachment = self.teleconsult_consent_attachment_id or self._teleconsult_create_consent_record()
        if not attachment:
            raise UserError(_("No telemedicine consent has been recorded yet."))
        return {'type': 'ir.actions.act_url', 'url': f'/web/content/{attachment.id}?download=true',
                'target': 'self'}

    def _teleconsult_notify_doctor(self):
        self.ensure_one()
        message = _("%(patient)s is waiting in the online waiting room for %(ref)s.",
                    patient=self.patient_id.name, ref=self.name)
        channel = self.sudo().teleconsult_channel_id
        if channel:
            channel.with_user(SUPERUSER_ID).message_post(
                body=Markup("<p>%s</p>") % message, message_type='comment', subtype_xmlid='mail.mt_comment')
        doctor_user = self._teleconsult_doctor_user()
        if doctor_user:
            doctor_user._bus_send('simple_notification', {
                'type': 'warning',
                'title': _("Patient waiting online"),
                'message': message,
                'sticky': True,
            })

    def _teleconsult_add_patient_member(self):
        self.ensure_one()
        appt = self.sudo()
        channel = appt._teleconsult_ensure_channel()
        if appt.teleconsult_partner_id:
            if appt.teleconsult_partner_id not in channel.channel_member_ids.partner_id:
                channel._add_members(partners=appt.teleconsult_partner_id, post_joined_message=False)
        elif appt.teleconsult_guest_id:
            if appt.teleconsult_guest_id not in channel.channel_member_ids.guest_id:
                channel._add_members(guests=appt.teleconsult_guest_id, post_joined_message=False)
        else:
            raise UserError(_("The patient has not entered the online waiting room yet."))
        return channel

    def _teleconsult_add_patient_files(self, notes=None, files=()):
        """Store what the patient shares before the call. `files` is a list of (filename, mimetype, bytes)
        already validated by the caller (see the controller). Returns the created attachments."""
        self.ensure_one()
        appt = self.sudo()
        vals = {}
        notes = (notes or '').strip()
        if notes:
            vals['teleconsult_patient_notes'] = notes[:4000]
        attachments = self.env['ir.attachment'].sudo()
        room = UPLOAD_MAX_FILES - len(appt.teleconsult_upload_ids)
        for filename, mimetype, content in list(files)[:max(room, 0)]:
            attachments |= attachments.create({
                'name': filename,
                'raw': content,
                'mimetype': mimetype,
                'res_model': self._name,
                'res_id': appt.id,
                'description': UPLOAD_MARKER,
            })
        if attachments:
            vals['teleconsult_upload_ids'] = [(4, att.id) for att in attachments]
        if vals:
            appt.write(vals)
            appt.message_post(body=_(
                "The patient shared %(count)s file(s)%(notes)s from the online waiting room.",
                count=len(attachments), notes=_(" and a description") if notes else ''))
        return attachments

    def _teleconsult_share_files_with_case(self):
        """On admit, give the clinical case the patient's description and files."""
        self.ensure_one()
        appt = self.sudo()
        case = appt.case_id
        if not case or not (appt.teleconsult_upload_ids or appt.teleconsult_patient_notes):
            return
        copies = [att.copy({'res_model': case._name, 'res_id': case.id}).id for att in appt.teleconsult_upload_ids]
        body = Markup("<p><b>%s</b></p>") % _("Shared by the patient before the online consultation")
        if appt.teleconsult_patient_notes:
            body += Markup("<p>%s</p>") % appt.teleconsult_patient_notes
        case.message_post(body=body, attachment_ids=copies, subtype_xmlid='mail.mt_note')

    def _teleconsult_prescription_pdfs(self):
        """(prescription, filename, pdf bytes) for each prescription of this visit."""
        self.ensure_one()
        report = self.env.ref('dental_pharmacy.action_report_dental_prescription', raise_if_not_found=False)
        if not report:
            return []
        result = []
        for rx in self._teleconsult_prescriptions():
            pdf, _type = self.env['ir.actions.report'].sudo()._render_qweb_pdf(report.report_name, [rx.id])
            result.append((rx, f"Prescription {rx.name}.pdf".replace('/', '-'), pdf))
        return result

    def action_teleconsult_send_summary(self):
        """Email the patient their visit summary (advice + prescriptions) and show it on their link."""
        self._teleconsult_check_clinician()
        template = self.env.ref('dental_teleconsult.mail_template_teleconsult_summary', raise_if_not_found=False)
        for appt in self:
            if appt.consultation_mode != 'online' or not appt.teleconsult_started_at:
                raise UserError(_("A visit summary can be sent once the online consultation has taken place."))
            if not appt.teleconsult_outcome or not appt.teleconsult_summary \
                    or not html2plaintext(appt.teleconsult_summary).strip():
                raise UserError(_("Set the consultation outcome and write the advice for the patient first."))
            appt.sudo().teleconsult_summary_sent_at = fields.Datetime.now()
            summary_pdf = appt._teleconsult_render_pdf(
                'dental_teleconsult.action_report_teleconsult_summary',
                _("Visit Summary - %s.pdf", appt.name), SUMMARY_MARKER)
            if summary_pdf:
                # Resending keeps earlier versions (they may already be filed in the patient record)
                appt.sudo().teleconsult_summary_attachment_id = summary_pdf
            if template and appt.patient_id.email:
                attachment_ids = summary_pdf.ids + [
                    self.env['ir.attachment'].sudo().create({
                        'name': filename, 'raw': pdf, 'mimetype': 'application/pdf',
                        'res_model': appt._name, 'res_id': appt.id,
                        'description': PRESCRIPTION_MARKER,
                    }).id
                    for _rx, filename, pdf in appt._teleconsult_prescription_pdfs()
                ]
                template.sudo().send_mail(appt.id, force_send=False,
                                          email_values={'attachment_ids': [(4, aid) for aid in attachment_ids]})
                appt.message_post(body=_("Visit summary emailed to %s.", appt.patient_id.email))
            else:
                appt.message_post(body=_("Visit summary published on the patient's consultation link "
                                         "(not emailed: no email address)."))
        return True

    # ---------------------------------------------------------
    # Doctor / front-desk actions
    # ---------------------------------------------------------
    def _teleconsult_room_action(self, channel):
        active_id = f"discuss.channel_{channel.id}"
        return {
            'type': 'ir.actions.client',
            'tag': 'mail.action_discuss',
            'name': channel.name,
            'params': {'active_id': active_id},
            'context': {'active_id': active_id, 'call': 'accept'},
        }

    def action_teleconsult_join(self):
        """Doctor/assistant enters the video room (and starts or joins the call)."""
        self.ensure_one()
        self._teleconsult_check_clinician()
        if self.consultation_mode != 'online' or self.teleconsult_state not in ACTIVE_ROOM_STATES:
            raise UserError(_("This appointment has no open online consultation room."))
        channel = self._teleconsult_ensure_channel()
        if self.env.user.partner_id not in channel.channel_member_ids.partner_id:
            channel._add_members(users=self.env.user, post_joined_message=False)
        return self._teleconsult_room_action(channel)

    def action_teleconsult_admit(self):
        """Admit the waiting patient into the call and start the consultation."""
        self.ensure_one()
        self._teleconsult_check_clinician()
        if self.teleconsult_state not in ('waiting', 'in_call'):
            raise UserError(_("The patient is not in the online waiting room."))
        self._teleconsult_add_patient_member()
        vals = {'teleconsult_state': 'in_call'}
        if not self.teleconsult_started_at:
            vals['teleconsult_started_at'] = fields.Datetime.now()
        self.sudo().write(vals)
        if self.state in ('confirmed', 'checked_in') and self._can_start_consultation():
            self.action_start_consultation()
        self._teleconsult_share_files_with_case()
        self.message_post(body=_("Patient admitted to the online consultation by %s.", self.env.user.name))
        return self.action_teleconsult_join()

    def action_teleconsult_end(self):
        self._teleconsult_check_clinician()
        for appt in self:
            if appt.teleconsult_state not in ('waiting', 'in_call'):
                raise UserError(_("There is no online consultation in progress for %s.", appt.name))
            appt._teleconsult_end_session(final_state='ended')
            appt.message_post(body=_("Online consultation ended by %(user)s after %(minutes)d minutes.",
                                     user=self.env.user.name, minutes=round(appt.teleconsult_duration)))
        return True

    def action_teleconsult_reopen(self):
        """Reopen an ended room (e.g. the call was ended by mistake) for the same visit."""
        self._teleconsult_check_clinician()
        for appt in self:
            if appt.teleconsult_state != 'ended' or appt.state in ('completed', 'cancelled', 'no_show'):
                raise UserError(_("Only an ended online consultation of an open visit can be reopened."))
            appt.sudo().write({'teleconsult_state': 'scheduled', 'teleconsult_ended_at': False})
            appt.message_post(body=_("Online consultation room reopened by %s.", self.env.user.name))
        return True

    def action_teleconsult_send_link(self):
        """(Re)send the join link. A new token is issued, so earlier links stop working."""
        self._teleconsult_check_front_desk()
        for appt in self:
            if appt.consultation_mode != 'online' or appt.state not in ('confirmed', 'checked_in', 'in_consultation'):
                raise UserError(_("Only confirmed online consultations have a join link."))
            appt.sudo().write({
                'teleconsult_access_token': secrets.token_urlsafe(32),
                'teleconsult_failed_verifications': 0,
            })
            appt._teleconsult_prepare()
            appt._teleconsult_send_invitation()
        return True

    def action_teleconsult_request_payment(self):
        self._teleconsult_check_front_desk()
        for appt in self:
            if not appt._teleconsult_ensure_payment_request():
                raise UserError(_("No consultation fee to request for %s.", appt.name))
        return True

    def action_teleconsult_waive_payment(self):
        user = self.env.user
        if not (user.has_group('dental_base.group_dental_manager') or user.has_group('dental_base.group_dental_admin')):
            raise AccessError(_("Only clinic managers can waive the online consultation fee."))
        for appt in self:
            appt.sudo().teleconsult_payment_waived = True
            appt.message_post(body=_("Online consultation fee waived by %s: the patient can join without paying.",
                                     user.name))
        return True

    # ---------------------------------------------------------
    # ORM & workflow hooks
    # ---------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        booking_mode = self.env.context.get('dental_teleconsult_booking_mode')
        if booking_mode:
            # Set by create_appointment_booking (website / booking flow), which builds its own vals
            for vals in vals_list:
                vals.setdefault('consultation_mode', booking_mode)
            self = self.with_context(dental_teleconsult_booking_mode=False)
        records = super().create(vals_list)
        records.filtered(lambda a: a.consultation_mode == 'online')._teleconsult_sync()
        return records

    def write(self, vals):
        old_doctors = {appt.id: appt.doctor_id for appt in self} if 'doctor_id' in vals else {}
        res = super().write(vals)
        if TELECONSULT_SYNC_FIELDS & set(vals):
            self._teleconsult_sync(old_doctors)
        return res

    def action_confirm(self):
        # Prepare the room and payment request first: the confirmation email (swapped for the
        # online invitation, see mail.template) needs the join and payment links.
        to_invite = self.filtered(lambda a: a.consultation_mode == 'online' and a.state == 'pending')
        to_invite._teleconsult_prepare()
        res = super(DentalAppointment, self.with_context(
            dental_teleconsult_confirming=True, dental_teleconsult_invite=True)).action_confirm()
        to_invite.filtered(lambda a: a.state == 'confirmed')._teleconsult_invitation_sent()
        return res

    @api.model
    def _cron_teleconsult_reminders(self):
        now = fields.Datetime.now()
        template = self.env.ref('dental_teleconsult.mail_template_teleconsult_reminder', raise_if_not_found=False)
        candidates = self.sudo().search([
            ('consultation_mode', '=', 'online'),
            ('state', 'in', ('confirmed', 'checked_in')),
            ('teleconsult_reminder_sent', '=', False),
            ('teleconsult_access_token', '!=', False),
            ('date_start', '>', now),
            ('date_start', '<=', now + timedelta(hours=3)),
        ])
        for appt in candidates:
            minutes = appt._teleconsult_company().dental_teleconsult_reminder_minutes
            if not minutes or appt.date_start > now + timedelta(minutes=minutes):
                continue
            appt._teleconsult_send_reminder(template)
            appt.teleconsult_reminder_sent = True

    def _teleconsult_send_reminder(self, template=None):
        """Send the "your consultation starts soon" reminder (extended by dental_teleconsult_sms)."""
        self.ensure_one()
        if template and self.patient_id.email:
            template.send_mail(self.id, force_send=False)

    # ---------------------------------------------------------
    # Website booking (dental_appointment / dental_website_appointment)
    # ---------------------------------------------------------
    @api.model
    def _teleconsult_booking_error(self, post):
        """Return why an online booking cannot be accepted, or False."""
        branch = self._resolve_booking_branch(post.get('branch_id'))
        if not branch.dental_teleconsult_enabled:
            return _("Online video consultations are not offered at %s. Please book an in-clinic visit.",
                     branch.name)
        type_id = post.get('appointment_type_id')
        if type_id:
            try:
                appt_type = self.env['dental.appointment.type'].sudo().browse(int(type_id)).exists()
            except (TypeError, ValueError):
                appt_type = self.env['dental.appointment.type']
            if appt_type and not appt_type.allow_online:
                return _("%s cannot be done as an online consultation. Please book an in-clinic visit.",
                         appt_type.name)
        return False

    @api.model
    def get_bookable_services(self, branch_id=None):
        """Flag the services that can be booked as an online consultation (staff booking flow)."""
        result = super().get_bookable_services(branch_id=branch_id)
        branch = self.env['res.company'].sudo().browse(result.get('branch_id')).exists()
        enabled = bool(branch.dental_teleconsult_enabled)
        types = self.env['dental.appointment.type'].sudo().browse(
            [s['appointment_type_id'] for s in result.get('services', []) if s.get('appointment_type_id')])
        allowed = set(types.filtered('allow_online').ids)
        for service in result.get('services', []):
            type_id = service.get('appointment_type_id')
            service['allow_online'] = enabled and (not type_id or type_id in allowed)
        result['teleconsult_enabled'] = enabled
        return result

    @api.model
    def create_appointment_booking(self, post=None, **kwargs):
        """Accept ``consultation_mode='online'`` from the website booking flow."""
        if not post and kwargs:
            post = kwargs.get('post') or kwargs
        post = dict(post or {})
        if post.get('consultation_mode') != 'online':
            return super().create_appointment_booking(post)
        error = self._teleconsult_booking_error(post)
        if error:
            return {'success': False, 'error': error}
        result = super(DentalAppointment, self.with_context(
            dental_teleconsult_booking_mode='online', dental_teleconsult_booking=True,
        )).create_appointment_booking(post)
        if result.get('success'):
            appt = self.sudo().browse(result['appointment_id'])
            result.update({
                'consultation_mode': 'online',
                'teleconsult_staff_message': (
                    _("Online video consultation booked. The join link was sent to the patient%(pay)s.",
                      pay=_(" with the payment request") if appt.teleconsult_payment_state == 'due' else '')
                    if appt.teleconsult_access_token else
                    _("Online video consultation requested. Confirm it to send the join link.")),
                'service_name': _("%s (online video)", result.get('service_name') or ''),
                'teleconsult_message': (
                    _("Your online video consultation is confirmed. Check your email for your secure "
                      "join link.") if appt.teleconsult_access_token else
                    _("The clinic will confirm your request shortly. You will then receive an email with "
                      "your secure join link and, if required, a link to pay the consultation fee.")),
            })
        return result

    # ---------------------------------------------------------
    # Display helpers for templates
    # ---------------------------------------------------------
    def _teleconsult_local_start(self):
        self.ensure_one()
        return self._teleconsult_format_dt(self.date_start, 'full')

    def _teleconsult_tz_label(self):
        self.ensure_one()
        tz = self._teleconsult_tz()
        try:
            return fields.Datetime.now().replace(tzinfo=pytz.utc).astimezone(pytz.timezone(tz)).strftime('%Z')
        except pytz.UnknownTimeZoneError:
            return tz
