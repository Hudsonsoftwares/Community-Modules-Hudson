# -*- coding: utf-8 -*-
from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.http import request
from odoo.http.stream import content_disposition
from odoo.tools import consteq


from odoo.tools.mimetypes import guess_mimetype

from odoo.addons.dental_teleconsult.models.dental_appointment import (
    MAX_FAILED_VERIFICATIONS, UPLOAD_MAX_BYTES, UPLOAD_MAX_FILES, UPLOAD_MIMETYPES,
)

SESSION_KEY = 'dental_teleconsult_verified'
# Stages in which the patient may share photos / a description with the dentist
SHARE_STAGES = ('early', 'ready', 'waiting')  # during the call, files go in the call chat
POLL_STAGES = {'waiting': 4000, 'in_call': 4000, 'payment': 15000, 'early': 20000, 'ready': 20000}


class DentalTeleconsultController(http.Controller):
    """Patient side of an online consultation: secure link -> identity -> payment -> waiting room -> call."""

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------
    def _get_appointment(self, token):
        if not token or len(token) < 32:
            raise NotFound()
        # sudo: dental.appointment - access is granted by the secret join token
        appt = request.env['dental.appointment'].sudo().search([('teleconsult_access_token', '=', token)], limit=1)
        if not appt or not consteq(appt.teleconsult_access_token, token):
            raise NotFound()
        return appt

    def _is_verified(self, appt):
        if appt._teleconsult_is_patient_user(request.env.user):
            return True
        if not appt._teleconsult_identity_method():
            return True
        return appt.teleconsult_access_token in request.session.get(SESSION_KEY, [])

    def _mark_verified(self, appt):
        verified = [t for t in request.session.get(SESSION_KEY, []) if t != appt.teleconsult_access_token]
        request.session[SESSION_KEY] = (verified + [appt.teleconsult_access_token])[-10:]

    def _stage(self, appt):
        if appt.consultation_mode != 'online' or appt.state in ('cancelled', 'no_show', 'pending') \
                or appt.teleconsult_state in (False, 'closed'):
            return 'closed'
        ended = appt.teleconsult_state == 'ended' or appt.state == 'completed'
        if ended and not appt.teleconsult_summary_sent_at:
            return 'ended'
        # The visit summary contains health information: same identity check as joining
        verified = self._is_verified(appt)
        if not verified and appt.teleconsult_failed_verifications >= MAX_FAILED_VERIFICATIONS:
            return 'locked'
        if not verified:
            return 'verify'
        if ended:
            return 'ended'
        if not appt._teleconsult_can_join():
            return 'payment'
        if appt.teleconsult_state == 'in_call':
            return 'in_call'
        if appt.teleconsult_state == 'waiting':
            return 'waiting'
        opens, closes = appt._teleconsult_window()
        now = fields.Datetime.now()
        if now < opens:
            return 'early'
        if now > closes:
            return 'expired'
        return 'ready'

    def _render(self, appt, error=None):
        stage = self._stage(appt)
        token = appt.teleconsult_access_token
        opens, _closes = appt._teleconsult_window()
        invoice = appt.teleconsult_invoice_id
        values = {
            'appointment': appt,
            'stage': stage,
            'error': error,
            'token': token,
            'base_path': f"/dental/teleconsult/{token}",
            'clinic': appt._teleconsult_company(),
            'doctor_name': appt.doctor_id.name,
            'start_label': appt._teleconsult_local_start(),
            'opens_label': appt._teleconsult_format_dt(opens, 'short'),
            'tz_label': appt._teleconsult_tz_label(),
            'identity_method': appt._teleconsult_identity_method(),
            'patient_has_account': bool(appt.patient_id.sudo().user_ids),
            'payment_url': appt.teleconsult_payment_url,
            'amount_due': invoice.amount_residual if invoice else 0.0,
            'currency': invoice.currency_id if invoice else appt._teleconsult_company().currency_id,
            'recording_allowed': appt._teleconsult_company().dental_teleconsult_allow_recording,
            'poll_interval': POLL_STAGES.get(stage, 0),
            'can_share_files': stage in SHARE_STAGES,
            'uploads': appt.teleconsult_upload_ids,
            'max_uploads': UPLOAD_MAX_FILES,
            'show_summary': stage == 'ended' and bool(appt.teleconsult_summary_sent_at),
            'outcome_label': dict(appt._fields['teleconsult_outcome']._description_selection(request.env)).get(
                appt.teleconsult_outcome, ''),
            'prescriptions': appt._teleconsult_prescriptions() if appt.teleconsult_summary_sent_at else [],
            'next_visit': self._next_visit(appt) if stage == 'ended' else False,
        }
        response = request.render('dental_teleconsult.teleconsult_lobby', values)
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        response.headers['Cache-Control'] = 'no-store'
        return response

    def _next_visit(self, appt):
        return request.env['dental.appointment'].sudo().search([
            ('patient_id', '=', appt.patient_id.id),
            ('id', '!=', appt.id),
            ('date_start', '>', appt.date_start),
            ('state', 'in', ('pending', 'confirmed')),
        ], order='date_start', limit=1)

    def _consent_info(self):
        httprequest = request.httprequest
        return {'ip': httprequest.remote_addr, 'user_agent': httprequest.user_agent.string if httprequest.user_agent else ''}

    def _room_url(self, appt):
        return f"/dental/teleconsult/{appt.teleconsult_access_token}/room"

    # ---------------------------------------------------------
    # Routes
    # ---------------------------------------------------------
    @http.route('/dental/teleconsult/<string:token>', type='http', auth='public', website=True,
                sitemap=False, methods=['GET'])
    def teleconsult_lobby(self, token, **kwargs):
        return self._render(self._get_appointment(token))

    @http.route('/dental/teleconsult/<string:token>/verify', type='http', auth='public', website=True,
                sitemap=False, methods=['POST'])
    def teleconsult_verify(self, token, dob=None, phone_digits=None, **kwargs):
        appt = self._get_appointment(token)
        if self._stage(appt) != 'verify':
            return request.redirect(f"/dental/teleconsult/{token}")
        if appt._teleconsult_check_identity(dob=dob, phone_digits=phone_digits):
            self._mark_verified(appt)
            return request.redirect(f"/dental/teleconsult/{token}")
        appt._teleconsult_register_failed_verification()
        return self._render(appt, error='identity')

    @http.route('/dental/teleconsult/<string:token>/ready', type='http', auth='public', website=True,
                sitemap=False, methods=['POST'])
    def teleconsult_ready(self, token, accept_terms=None, accept_recording=None, **kwargs):
        appt = self._get_appointment(token)
        if self._stage(appt) != 'ready':
            return request.redirect(f"/dental/teleconsult/{token}")
        if not accept_terms:
            return self._render(appt, error='terms')
        partner = guest = None
        if appt._teleconsult_is_patient_user(request.env.user):
            partner = request.env.user.partner_id
        else:
            guest = appt.teleconsult_guest_id
            if not guest:
                # sudo: mail.guest - the verified patient gets a guest identity for the video room
                guest = request.env['mail.guest'].sudo().create({
                    'name': appt.patient_id.name,
                    'lang': appt.patient_id.lang or request.env.lang,
                    'timezone': request.env['mail.guest']._get_timezone_from_request(request),
                })
            guest.sudo()._set_auth_cookie()
        recording = bool(accept_recording) and appt._teleconsult_company().dental_teleconsult_allow_recording
        appt._teleconsult_patient_ready(guest=guest, partner=partner, recording_consent=recording,
                                        consent_info=self._consent_info())
        return request.redirect(f"/dental/teleconsult/{token}")

    @http.route('/dental/teleconsult/<string:token>/share', type='http', auth='public', website=True,
                sitemap=False, methods=['POST'])
    def teleconsult_share(self, token, patient_notes=None, **kwargs):
        appt = self._get_appointment(token)
        if self._stage(appt) not in SHARE_STAGES:
            return request.redirect(f"/dental/teleconsult/{token}")
        files, rejected = [], 0
        for storage in request.httprequest.files.getlist('files'):
            if not storage or not storage.filename:
                continue
            content = storage.read(UPLOAD_MAX_BYTES + 1)
            mimetype = guess_mimetype(content)
            if not content or len(content) > UPLOAD_MAX_BYTES or mimetype not in UPLOAD_MIMETYPES:
                rejected += 1
                continue
            filename = storage.filename.replace('\\', '/').rsplit('/', 1)[-1][:120] or 'upload'
            files.append((filename, mimetype, content))
        appt._teleconsult_add_patient_files(notes=patient_notes, files=files)
        if rejected:
            return self._render(appt, error='files_rejected')
        return request.redirect(f"/dental/teleconsult/{token}")

    @http.route('/dental/teleconsult/<string:token>/prescription/<int:prescription_id>', type='http',
                auth='public', sitemap=False, methods=['GET'])
    def teleconsult_prescription(self, token, prescription_id, **kwargs):
        appt = self._get_appointment(token)
        if self._stage(appt) != 'ended' or not appt.teleconsult_summary_sent_at:
            raise NotFound()
        for rx, filename, pdf in appt._teleconsult_prescription_pdfs():
            if rx.id == prescription_id:
                return request.make_response(pdf, headers=[
                    ('Content-Type', 'application/pdf'),
                    ('Content-Length', len(pdf)),
                    ('Content-Disposition', content_disposition(filename)),
                    ('Cache-Control', 'no-store'),
                ])
        raise NotFound()

    @http.route('/dental/teleconsult/<string:token>/status', type='http', auth='public',
                sitemap=False, methods=['GET'])
    def teleconsult_status(self, token, **kwargs):
        appt = self._get_appointment(token)
        stage = self._stage(appt)
        payload = {'stage': stage}
        if stage == 'in_call':
            payload['room_url'] = self._room_url(appt)
        return request.make_json_response(payload, headers={'Cache-Control': 'no-store'})

    @http.route('/dental/teleconsult/<string:token>/room', type='http', auth='public', website=True,
                sitemap=False, methods=['GET'])
    def teleconsult_room(self, token, **kwargs):
        appt = self._get_appointment(token)
        if self._stage(appt) != 'in_call':
            return request.redirect(f"/dental/teleconsult/{token}")
        channel = appt.teleconsult_channel_id
        if appt.teleconsult_partner_id and request.env.user.partner_id == appt.teleconsult_partner_id:
            pass  # portal patient joins with their own account
        elif appt.teleconsult_guest_id and not appt._teleconsult_is_patient_user(request.env.user):
            appt.teleconsult_guest_id.sudo()._set_auth_cookie()
        else:
            # Same verified patient on another device / login: give this browser a persona too
            partner = request.env.user.partner_id if appt._teleconsult_is_patient_user(request.env.user) else None
            guest = None
            if not partner:
                guest = request.env['mail.guest'].sudo().create({'name': appt.patient_id.name})
                guest._set_auth_cookie()
            appt._teleconsult_patient_ready(guest=guest, partner=partner,
                                            recording_consent=appt.teleconsult_recording_consent)
        appt._teleconsult_add_patient_member()
        return request.redirect(f"/discuss/channel/{channel.id}")
