"""HIP flows on top of the ABDM gateway client.

Outgoing calls use ``abdm.gateway._request`` / ``_send_async``; incoming
callbacks arrive through ``_handle_callback`` (see abdm_base controller).
"""
import hashlib
import json
import logging
import re
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.abdm_base.tools import fidelius

from .. import const
from .abdm_consent import _parse_dt

_logger = logging.getLogger(__name__)


def _iso(dt=None):
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def _header(headers, name):
    for key, value in (headers or {}).items():
        if key.lower() == name.lower():
            return value
    return None


class AbdmGateway(models.AbstractModel):
    _inherit = 'abdm.gateway'

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @api.model
    def _hip_headers(self, company, **extra):
        if not company.abdm_hip_id:
            raise UserError(self.env._("Facility %s has no ABDM Facility ID (HFR).", company.display_name))
        headers = {'X-HIP-ID': company.abdm_hip_id}
        headers.update({k.replace('_', '-'): v for k, v in extra.items() if v})
        return headers

    @api.model
    def _hip_company_for(self, headers):
        hip_id = _header(headers, 'X-HIP-ID')
        Company = self.env['res.company'].sudo()
        if hip_id:
            company = Company.search([('abdm_hip_id', '=', hip_id)], limit=1)
            if company:
                return company
        companies = Company.search([('abdm_hip_id', '!=', False)])
        return companies[:1] if len(companies) == 1 else Company.browse()

    @api.model
    def _hip_reply(self, path, body, incoming_headers, company=None):
        """Answer an ABDM callback (on-discover, on-init...)."""
        body = dict(body, response={'requestId': _header(incoming_headers, 'REQUEST-ID')})
        headers = {'X-HIP-ID': company.abdm_hip_id} if company and company.abdm_hip_id else None
        return self._request('POST', path, body, headers=headers, raise_on_error=False)

    @staticmethod
    def _hip_group_by_type(partner, contexts):
        """ABDM V3 lists care contexts grouped by health-information type."""
        groups = OrderedDict()
        for cc in contexts:
            for hi_type in cc._hi_type_list() or ['OPConsultation']:
                groups.setdefault(hi_type, []).append(cc)
        return [{
            'referenceNumber': partner._abdm_patient_reference(),
            'display': partner.name,
            'careContexts': [{'referenceNumber': cc.reference, 'display': cc.display} for cc in ccs],
            'hiType': hi_type,
            'count': len(ccs),
        } for hi_type, ccs in groups.items()]

    # ------------------------------------------------------------------
    # 1. Clinic-initiated linking
    # ------------------------------------------------------------------
    @api.model
    def _hip_link_care_contexts(self, contexts):
        contexts = contexts.sudo()
        groups = {}
        for cc in contexts:
            groups.setdefault((cc.partner_id, cc.company_id), self.env['abdm.care.context'].sudo())
            groups[(cc.partner_id, cc.company_id)] |= cc
        for (partner, company), ccs in groups.items():
            ccs.write({'state': 'linking', 'error_message': False})
            token = self.env['abdm.link.token']._get_valid(partner, company.abdm_hip_id)
            if token:
                self._hip_send_link(ccs, token)
            else:
                self._hip_request_link_token(partner, company, ccs)

    @api.model
    def _hip_request_link_token(self, partner, company, contexts):
        demo = partner._abdm_demographics()
        if not demo.get('year_of_birth'):
            contexts.write({'state': 'not_linked'})
            raise UserError(self.env._(
                "ABDM needs the year of birth of %s to link records. Enter the date of birth first.",
                partner.display_name))
        payload = {
            'abhaNumber': re.sub(r'\D', '', partner.abha_number or '') or None,
            'abhaAddress': partner.abha_address or None,
            'name': demo.get('name') or partner.name,
            'gender': demo.get('gender') or 'O',
            'yearOfBirth': int(demo['year_of_birth']) if demo.get('year_of_birth') else None,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        try:
            return self._send_async('hip.link_token', const.PATH_GENERATE_LINK_TOKEN, payload,
                                    headers=self._hip_headers(company), record=partner,
                                    context_data={'care_context_ids': contexts.ids, 'company_id': company.id})
        except UserError as exc:
            contexts.write({'state': 'error', 'error_message': str(exc)})
            raise

    @api.model
    def _hip_send_link(self, contexts, token):
        partner, company = contexts[:1].partner_id, contexts[:1].company_id
        payload = {
            'abhaNumber': re.sub(r'\D', '', partner.abha_number or '') or None,
            'abhaAddress': partner.abha_address or None,
            'patient': self._hip_group_by_type(partner, contexts),
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        try:
            return self._send_async('hip.link_care_context', const.PATH_LINK_CARE_CONTEXT, payload,
                                    headers=self._hip_headers(company, X_LINK_TOKEN=token), record=partner,
                                    context_data={'care_context_ids': contexts.ids, 'company_id': company.id})
        except UserError as exc:
            contexts.write({'state': 'error', 'error_message': str(exc)})
            raise

    @api.model
    def _hip_contexts_of(self, tx):
        ids = (tx.context_data or {}).get('care_context_ids') or []
        return self.env['abdm.care.context'].sudo().browse(ids).exists()

    @api.model
    def _hip_on_generate_token(self, tx, payload):
        contexts = self._hip_contexts_of(tx)
        if payload.get('error') or not payload.get('linkToken'):
            contexts.write({'state': 'error', 'error_message': tx.error_message or 'No link token'})
            return
        partner = self.env['res.partner'].sudo().browse(tx.res_id)
        company = self.env['res.company'].sudo().browse((tx.context_data or {}).get('company_id'))
        self.env['abdm.link.token']._store(partner, company.abdm_hip_id, payload['linkToken'],
                                           payload.get('abhaAddress'))
        if contexts:
            self._hip_send_link(contexts, payload['linkToken'])

    @api.model
    def _hip_on_link_care_context(self, tx, payload):
        contexts = self._hip_contexts_of(tx)
        if payload.get('error'):
            contexts.write({'state': 'error', 'error_message': tx.error_message})
            return
        contexts._set_linked('hip', payload.get('abhaAddress'))

    @api.model
    def _hip_notify_context(self, care_context):
        """Tell ABDM a linked care context has new records."""
        cc = care_context.sudo()
        if cc.state != 'linked':
            raise UserError(self.env._("Link the care context to ABHA first."))
        self._request('POST', const.PATH_CONTEXT_NOTIFY, {'notification': {
            'patient': {'id': cc.linked_abha_address or cc.partner_id.abha_address},
            'careContextReference': cc.reference,
            'hiTypes': cc._hi_type_list(),
            'date': _iso(),
            'hip': {'id': cc.company_id.abdm_hip_id},
        }}, headers=self._hip_headers(cc.company_id))
        cc.last_notified = fields.Datetime.now()

    # ------------------------------------------------------------------
    # 2. Patient-initiated linking (from the ABHA / PHR app)
    # ------------------------------------------------------------------
    @api.model
    def _hip_on_discover(self, payload, headers):
        company = self._hip_company_for(headers)
        transaction_id = payload.get('transactionId')
        partner, matched_by = self.env['res.partner']._abdm_find_patient(payload.get('patient') or {})
        contexts = self.env['abdm.care.context']
        if partner:
            for source in partner._abdm_care_context_sources(company):
                if source._abdm_health_records():
                    contexts |= source._abdm_ensure_care_context()
            contexts = contexts.filtered(lambda c: c.state != 'linked')
        if not partner or not contexts:
            body = {'transactionId': transaction_id, 'error': {
                'code': 'ABDM-1010' if not partner else 'ABDM-1011',
                'message': 'Patient not found' if not partner else 'No new records to link',
            }}
        else:
            body = {'transactionId': transaction_id, 'patient': self._hip_group_by_type(partner, contexts),
                    'matchedBy': matched_by}
        self._hip_reply(const.PATH_ON_DISCOVER, body, headers, company)

    @api.model
    def _hip_on_link_init(self, payload, headers):
        company = self._hip_company_for(headers)
        refs = [c.get('referenceNumber') for p in payload.get('patient') or []
                for c in p.get('careContexts') or [] if c.get('referenceNumber')]
        domain = [('reference', 'in', refs)] + ([('company_id', '=', company.id)] if company else [])
        contexts = self.env['abdm.care.context'].sudo().search(domain)
        partner = contexts[:1].partner_id
        transaction_id = payload.get('transactionId')
        if not contexts or len(contexts.partner_id) != 1:
            return self._hip_reply(const.PATH_ON_INIT, {'transactionId': transaction_id, 'error': {
                'code': 'ABDM-1012', 'message': 'Care context not found'}}, headers, company)
        request = self.env['abdm.link.request'].sudo().create({
            'transaction_id': transaction_id, 'partner_id': partner.id,
            'abha_address': payload.get('abhaAddress'), 'care_context_ids': [(6, 0, contexts.ids)],
        })
        otp = request._issue_otp()
        self._hip_send_otp(partner, otp, company)
        self._hip_reply(const.PATH_ON_INIT, {'transactionId': transaction_id, 'link': {
            'referenceNumber': request.link_reference,
            'authenticationType': 'DIRECT',
            'meta': {'communicationMedium': 'MOBILE', 'communicationHint': 'OTP',
                     'communicationExpiry': _iso(datetime.now(timezone.utc)
                                                 + timedelta(minutes=const.OTP_VALIDITY_MINUTES))},
        }}, headers, company)

    @api.model
    def _hip_send_otp(self, partner, otp, company):
        body = self.env._("%(otp)s is your OTP to link your health records at %(clinic)s with your ABHA. "
                          "Valid for %(minutes)s minutes. Do not share it.",
                          otp=otp, clinic=company.name if company else '', minutes=const.OTP_VALIDITY_MINUTES)
        if partner.phone and hasattr(partner, '_message_sms'):
            try:
                partner._message_sms(body, partner_ids=partner.ids)
                return True
            except Exception:  # noqa: BLE001 - no SMS credits must not break the ABDM flow
                _logger.warning("Could not send ABDM link OTP by SMS to partner %s", partner.id, exc_info=True)
        return False

    @api.model
    def _hip_on_link_confirm(self, payload, headers):
        company = self._hip_company_for(headers)
        confirmation = payload.get('confirmation') or {}
        request = self.env['abdm.link.request'].sudo().search(
            [('link_reference', '=', confirmation.get('linkRefNumber'))], limit=1)
        if not request or not request._check_otp(confirmation.get('token')):
            return self._hip_reply(const.PATH_ON_CONFIRM, {'error': {
                'code': 'ABDM-1013', 'message': 'Invalid or expired OTP'}}, headers, company)
        request.write({'state': 'linked', 'sandbox_otp': False})
        request.care_context_ids._set_linked('patient', request.abha_address)
        self._hip_reply(const.PATH_ON_CONFIRM, {
            'patient': self._hip_group_by_type(request.partner_id, request.care_context_ids),
        }, headers, company)

    # ------------------------------------------------------------------
    # 3. Consent and data transfer
    # ------------------------------------------------------------------
    @api.model
    def _hip_on_consent_notify(self, payload, headers):
        notification = payload.get('notification') or {}
        consent = self.env['abdm.consent']._from_notification(notification)
        self._hip_reply(const.PATH_CONSENT_ON_NOTIFY, {
            'acknowledgement': {'status': 'ok', 'consentId': consent.consent_id},
        }, headers, consent.company_id)

    @api.model
    def _hip_on_hi_request(self, payload, headers):
        hi_request = payload.get('hiRequest') or {}
        transaction_id = payload.get('transactionId')
        consent_id = (hi_request.get('consent') or {}).get('id')
        consent = self.env['abdm.consent'].sudo().search([('consent_id', '=', consent_id)], limit=1)
        date_range = hi_request.get('dateRange') or {}
        transfer = self.env['abdm.data.transfer'].sudo().create({
            'transaction_id': transaction_id, 'consent_id': consent_id,
            'consent_ref_id': consent.id or False,
            'data_push_url': hi_request.get('dataPushUrl'),
            'date_from': _parse_dt(date_range.get('from')), 'date_to': _parse_dt(date_range.get('to')),
        })
        error = None
        if not consent or not consent._is_usable():
            error = {'code': 'ABDM-1020', 'message': 'Consent not found, revoked or expired'}
        elif not hi_request.get('dataPushUrl') or not hi_request.get('keyMaterial'):
            error = {'code': 'ABDM-1021', 'message': 'Missing dataPushUrl or keyMaterial'}
        company = consent.company_id if consent else self._hip_company_for(headers)
        if error:
            transfer.write({'state': 'failed', 'error_message': error['message']})
            return self._hip_reply(const.PATH_HI_ON_REQUEST, {
                'hiRequest': {'transactionId': transaction_id, 'sessionStatus': 'ERROR'},
                'error': error}, headers, company)
        self._hip_reply(const.PATH_HI_ON_REQUEST, {
            'hiRequest': {'transactionId': transaction_id, 'sessionStatus': 'ACKNOWLEDGED'},
        }, headers, company)
        self._hip_transfer(transfer, consent, hi_request)

    @api.model
    def _hip_transfer(self, transfer, consent, hi_request):
        """Build, encrypt and push the consented records, then notify ABDM."""
        key_material = hi_request['keyMaterial']
        peer_key = (key_material.get('dhPublicKey') or {}).get('keyValue')
        peer_nonce = key_material.get('nonce')
        own = fidelius.KeyMaterial()
        hi_types = [t for t in (consent.hi_types or '').split(',') if t] or None
        date_from = max(filter(None, [consent.date_from, transfer.date_from]), default=None)
        date_to = min(filter(None, [consent.date_to, transfer.date_to]), default=None)

        entries, statuses = [], []
        for cc in consent.care_context_ids:
            try:
                records = cc._abdm_records(hi_types=hi_types, date_from=date_from, date_to=date_to)
                for record in records:
                    plain = json.dumps(record['bundle'], ensure_ascii=False)
                    entries.append({
                        'content': fidelius.encrypt(plain, own, peer_key, peer_nonce),
                        'media': 'application/fhir+json',
                        'checksum': hashlib.md5(plain.encode()).hexdigest(),
                        'careContextReference': cc.reference,
                    })
                statuses.append({'careContextReference': cc.reference, 'hiStatus': 'OK',
                                 'description': '%s record(s)' % len(records)})
            except Exception as exc:  # noqa: BLE001 - report per care context, keep the others
                _logger.exception("ABDM: could not build records for care context %s", cc.reference)
                statuses.append({'careContextReference': cc.reference, 'hiStatus': 'ERRORED',
                                 'description': str(exc)[:200]})

        push_ok, error = False, None
        try:
            status, body = self._hip_push(transfer.data_push_url, {
                'pageNumber': 1, 'pageCount': 1, 'transactionId': transfer.transaction_id,
                'entries': entries, 'keyMaterial': own.to_abdm(),
            })
            push_ok = 200 <= status < 300
            error = None if push_ok else self._extract_error(body, status)
        except UserError as exc:
            error = str(exc)
        for st in statuses:
            if st['hiStatus'] == 'OK':
                st['hiStatus'] = 'DELIVERED' if push_ok else 'ERRORED'
        transfer.write({
            'state': 'transferred' if push_ok else 'failed',
            'record_count': len(entries) if push_ok else 0,
            'details': '\n'.join('%(careContextReference)s: %(hiStatus)s (%(description)s)' % s for s in statuses),
            'error_message': error or False,
        })
        hip_id = consent.hip_id or consent.company_id.abdm_hip_id
        self._request('POST', const.PATH_HI_NOTIFY, {'notification': {
            'consentId': consent.consent_id,
            'transactionId': transfer.transaction_id,
            'doneAt': _iso(),
            'notifier': {'type': 'HIP', 'id': hip_id},
            'statusNotification': {
                'sessionStatus': 'TRANSFERRED' if push_ok else 'FAILED',
                'hipId': hip_id,
                'statusResponses': statuses,
            },
        }}, headers={'X-HIP-ID': hip_id} if hip_id else None, raise_on_error=False)

    @api.model
    def _hip_push(self, url, body):
        """POST the encrypted records to the requester's dataPushUrl."""
        if not url or not url.startswith('https://'):
            raise UserError(self.env._("Invalid dataPushUrl: %s", url))
        config = self._check_config()
        headers = {}
        if (urlparse(url).hostname or '').endswith('abdm.gov.in'):
            headers['Authorization'] = 'Bearer %s' % self._get_access_token()
        return self._send('POST', url, config=config, payload=body, headers=headers,
                          log_endpoint='push:%s' % urlparse(url).path)

    # ------------------------------------------------------------------
    # dispatch
    # ------------------------------------------------------------------
    @api.model
    def _handle_callback(self, path, payload, headers):
        tx = super()._handle_callback(path, payload, headers)
        if not isinstance(payload, dict):
            return tx
        if path.endswith(const.CB_ON_GENERATE_TOKEN):
            if tx and tx.operation == 'hip.link_token':
                self._hip_on_generate_token(tx, payload)
        elif path.endswith(const.CB_ON_LINK_CARE_CONTEXT):
            if tx and tx.operation == 'hip.link_care_context':
                self._hip_on_link_care_context(tx, payload)
        elif path.endswith(const.CB_DISCOVER):
            self._hip_on_discover(payload, headers)
        elif path.endswith(const.CB_LINK_INIT):
            self._hip_on_link_init(payload, headers)
        elif path.endswith(const.CB_LINK_CONFIRM):
            self._hip_on_link_confirm(payload, headers)
        elif path.endswith(const.CB_CONSENT_NOTIFY):
            self._hip_on_consent_notify(payload, headers)
        elif path.endswith(const.CB_HI_REQUEST):
            self._hip_on_hi_request(payload, headers)
        return tx
