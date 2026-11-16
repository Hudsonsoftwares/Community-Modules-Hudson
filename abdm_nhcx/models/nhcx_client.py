"""Client for the National Health Claims Exchange (NHCX).

Outgoing: ``send_request()`` encrypts a FHIR bundle for the recipient payer
and posts it to the exchange; an ``abdm.transaction`` (REQUEST-ID = HCX
correlation ID) waits for the answer.

Incoming: the exchange calls ``<public URL>/nhcx/<action>`` (see the
controller); ``handle_callback()`` decrypts the payload with the company's
private key, matches the transaction and hands the FHIR answer to the record
that asked (``record._nhcx_on_response()``).

HTTP, logging (``abdm.api.log``) and masking reuse ``abdm.gateway._send``.
"""
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

from odoo import api, models
from odoo.exceptions import UserError

from odoo.addons.abdm_base.models.abdm_gateway import AbdmError

from .. import const
from ..tools import jwe

_logger = logging.getLogger(__name__)

_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE = {}   # (db, token_url, username) -> (token, expires_at)


def _now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (now.microsecond // 1000)


class NhcxClient(models.AbstractModel):
    _name = 'nhcx.client'
    _description = 'NHCX Client'

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    @api.model
    def _get_config(self):
        ICP = self.env['ir.config_parameter'].sudo()
        base = self.env['abdm.gateway']._get_config()
        return dict(
            base,
            api_url=(ICP.get_str('abdm_nhcx.api_url') or '').strip().rstrip('/'),
            auth_mode=ICP.get_str('abdm_nhcx.auth_mode') or 'abdm',
            token_url=(ICP.get_str('abdm_nhcx.token_url') or '').strip(),
            username=(ICP.get_str('abdm_nhcx.username') or '').strip(),
            secret=(ICP.get_str('abdm_nhcx.secret') or '').strip(),
        )

    @api.model
    def _check_config(self):
        config = self._get_config()
        if not config['api_url']:
            raise UserError(self.env._(
                "NHCX is not configured: enter the NHCX API URL in Settings > ABDM > NHCX "
                "(it is in your NHCX onboarding kit)."))
        if config['auth_mode'] == 'token' and not (config['token_url'] and config['username']
                                                   and config['secret']):
            raise UserError(self.env._(
                "NHCX login: enter the Token URL, username and secret in Settings > ABDM > NHCX."))
        return config

    @api.model
    def _company_participant(self, company):
        """(participant code, private key) of a company, or a clear error."""
        company = company.sudo()
        if not company.nhcx_participant_code:
            raise UserError(self.env._(
                "%s has no NHCX participant code. Enter it in Settings > ABDM > NHCX.",
                company.display_name))
        if not company.nhcx_private_key:
            raise UserError(self.env._(
                "%s has no NHCX encryption keys. Generate them in Settings > ABDM > NHCX.",
                company.display_name))
        return company.nhcx_participant_code, jwe.load_private_key(company.nhcx_private_key)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    @api.model
    def _get_token(self, config, force_refresh=False):
        if config['auth_mode'] == 'abdm':
            # NHCX roles are attached to the ABDM client: same session token.
            return self.env['abdm.gateway']._get_access_token(force_refresh=force_refresh)
        key = (self.env.cr.dbname, config['token_url'], config['username'])
        if not force_refresh:
            with _TOKEN_LOCK:
                cached = _TOKEN_CACHE.get(key)
            if cached and cached[1] > time.time():
                return cached[0]
        status, body = self.env['abdm.gateway']._send(
            'POST', config['token_url'], config=config, abdm_headers=False,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            data=urlencode({'username': config['username'], 'secret': config['secret']}),
            log_body={'username': config['username'], 'secret': '***'},
            log_endpoint='nhcx:token',
        )
        token = isinstance(body, dict) and (body.get('access_token') or body.get('accessToken'))
        if not (200 <= status < 300) or not token:
            raise AbdmError(self.env._(
                "NHCX refused the login (HTTP %(status)s): %(error)s",
                status=status, error=self.env['abdm.gateway']._extract_error(body, status)),
                status_code=status, data=body)
        expires_in = int(body.get('expires_in') or body.get('expiresIn') or 600)
        with _TOKEN_LOCK:
            _TOKEN_CACHE[key] = (token, time.time() + max(expires_in - const.TOKEN_EXPIRY_MARGIN, 30))
        return token

    @api.model
    def _post(self, path, body, *, log_body=None, request_id=None):
        """Authenticated POST to the exchange. Returns (status, body)."""
        config = self._check_config()
        gateway = self.env['abdm.gateway']
        status, answer = None, None
        for attempt in range(2):
            token = self._get_token(config, force_refresh=attempt > 0)
            status, answer = gateway._send(
                'POST', config['api_url'] + path, config=config, payload=body,
                headers={'Authorization': 'Bearer %s' % token}, abdm_headers=False,
                request_id=request_id, log_body=log_body, log_endpoint='nhcx:%s' % path,
            )
            if status != 401:
                break
        return status, answer

    @api.model
    def test_connection(self):
        config = self._check_config()
        self._get_token(config, force_refresh=True)
        return config

    # ------------------------------------------------------------------
    # Sending a request
    # ------------------------------------------------------------------
    @api.model
    def _recipient_key(self, payer):
        payer = payer.sudo()
        if not payer.nhcx_participant_code:
            raise UserError(self.env._(
                "%s has no NHCX participant code. Sync the payers from NHCX or enter it on the "
                "insurance company.", payer.display_name))
        if not payer.nhcx_encryption_cert:
            payer.action_nhcx_refresh()
        return jwe.load_public_key(payer.nhcx_encryption_cert)

    @api.model
    def send_request(self, path, fhir_bundle, *, payer, company, record, operation,
                     workflow_id=None, correlation_id=None):
        """Encrypt ``fhir_bundle`` for ``payer`` and send it to the exchange.

        Returns the ``abdm.transaction`` waiting for the answer. Raises
        UserError (AbdmError) when the exchange refuses the request.
        """
        sender_code, _key = self._company_participant(company)
        public_key = self._recipient_key(payer)
        correlation_id = correlation_id or str(uuid.uuid4())
        api_call_id = str(uuid.uuid4())
        workflow_id = workflow_id or str(uuid.uuid4())
        headers = {
            const.H_API_CALL_ID: api_call_id,
            const.H_CORRELATION_ID: correlation_id,
            const.H_WORKFLOW_ID: workflow_id,
            const.H_SENDER: sender_code,
            const.H_RECIPIENT: payer.sudo().nhcx_participant_code,
            const.H_TIMESTAMP: _now_iso(),
            const.H_STATUS: const.STATUS_REQUEST,
        }
        token = jwe.encrypt(fhir_bundle, headers, public_key)

        tx = self.env['abdm.transaction'].sudo().create({
            'operation': operation,
            'request_id': correlation_id,
            'res_model': record._name,
            'res_id': record.id,
            'company_id': company.id,
            'context_data': {'api_call_id': api_call_id, 'workflow_id': workflow_id,
                             'recipient_code': headers[const.H_RECIPIENT], 'path': path},
        })
        tx._set_request(fhir_bundle)
        try:
            status, answer = self._post(
                path, {'payload': token}, request_id=correlation_id,
                log_body={'protected_header': headers, 'payload': '<encrypted FHIR bundle, see transaction>'})
        except UserError as exc:
            tx._set_error(exc.args[0] if exc.args else exc)
            raise
        if not (200 <= status < 300):
            error = self._error_text(answer, status)
            tx._set_error(error)
            raise AbdmError(self.env._("NHCX refused the request (HTTP %(status)s): %(error)s",
                                       status=status, error=error), status_code=status, data=answer)
        return tx

    @api.model
    def _error_text(self, body, status=None):
        if isinstance(body, dict):
            details = body.get(const.H_ERROR) or body.get('error')
            if isinstance(details, dict):
                parts = [details.get('code'), details.get('message'), details.get('trace')]
                return ' '.join(str(p) for p in parts if p) or json.dumps(details)
            if details:
                return str(details)
        return self.env['abdm.gateway']._extract_error(body, status)

    # ------------------------------------------------------------------
    # Participant registry
    # ------------------------------------------------------------------
    @api.model
    def participant_search(self, filters):
        status, answer = self._post(const.PATH_PARTICIPANT_SEARCH, {'filters': filters})
        if not (200 <= status < 300):
            raise AbdmError(self.env._("NHCX participant search failed (HTTP %(status)s): %(error)s",
                                       status=status, error=self._error_text(answer, status)),
                            status_code=status, data=answer)
        participants = answer.get('participants') if isinstance(answer, dict) else answer
        return participants or []

    @api.model
    def fetch_certificate(self, value):
        """Participants publish their encryption certificate as PEM or as a URL."""
        if not value:
            return False
        if not value.strip().lower().startswith('http'):
            return value.strip()
        config = self._get_config()
        status, body = self.env['abdm.gateway']._send(
            'GET', value.strip(), config=config, abdm_headers=False, raw=True,
            log_endpoint='nhcx:certificate')
        if not (200 <= status < 300) or not isinstance(body, bytes):
            raise AbdmError(self.env._("Could not download the certificate %(url)s (HTTP %(status)s).",
                                       url=value, status=status), status_code=status)
        return body.decode('utf-8', errors='replace').strip()

    @api.model
    def sync_payers(self):
        """Create / update insurance companies and TPAs from the NHCX registry."""
        Partner = self.env['res.partner'].sudo()
        count = 0
        for role, partner_type in ((const.ROLE_PAYER, 'insurer'), (const.ROLE_TPA, 'tpa')):
            for participant in self.participant_search({'roles': {'eq': role}}):
                code = participant.get('participant_code')
                if not code:
                    continue
                Partner._nhcx_upsert_participant(participant, partner_type)
                count += 1
        return count

    # ------------------------------------------------------------------
    # Incoming callbacks
    # ------------------------------------------------------------------
    @api.model
    def handle_callback(self, action, body):
        """Process one call of the exchange on our endpoint.

        :param action: path after /nhcx/, e.g. ``coverageeligibility/on_check``
        :param body: parsed JSON body
        :return: (http status, acknowledgement dict, error text or None)
        """
        if not isinstance(body, dict):
            return 400, {'error': 'body must be a JSON object'}, 'body is not a JSON object'
        encrypted = body.get('payload')
        payload = None
        if encrypted:
            try:
                headers = jwe.read_header(encrypted)
            except jwe.JweError as exc:
                return 400, {'error': str(exc)}, str(exc)
            company = self.env['res.company'].sudo().search(
                [('nhcx_participant_code', '=', headers.get(const.H_RECIPIENT))], limit=1)
            if not company or not company.nhcx_private_key:
                error = 'unknown recipient %s' % headers.get(const.H_RECIPIENT)
                return 400, {'error': error}, error
            try:
                headers, payload = jwe.decrypt(encrypted, jwe.load_private_key(company.nhcx_private_key))
            except jwe.JweError as exc:
                return 400, {'error': 'cannot decrypt payload'}, str(exc)
        else:
            # Errors and acknowledgements come as plain protocol headers.
            headers = {k: v for k, v in body.items() if k.startswith('x-hcx-')}

        correlation_id = headers.get(const.H_CORRELATION_ID)
        ack = {'timestamp': int(time.time()), 'correlation_id': correlation_id,
               'api_call_id': headers.get(const.H_API_CALL_ID)}
        tx = self.env['abdm.transaction']._find_by_request_id(correlation_id)
        if not tx:
            return 202, ack, 'no request with correlation ID %s (ignored)' % correlation_id
        expected_sender = (tx.context_data or {}).get('recipient_code')
        if expected_sender and headers.get(const.H_SENDER) != expected_sender:
            error = 'sender %s does not match the payer %s of the request' % (
                headers.get(const.H_SENDER), expected_sender)
            return 403, {'error': 'sender mismatch'}, error

        status = headers.get(const.H_STATUS)
        error = None
        if status == const.STATUS_ERROR or headers.get(const.H_ERROR):
            error = self._error_text({const.H_ERROR: headers.get(const.H_ERROR) or status})
        tx._set_response({'headers': headers, 'payload': payload, 'error': error} if error
                         else {'headers': headers, 'payload': payload}, callback_path='/nhcx/' + action)
        record = self.env[tx.res_model].sudo().browse(tx.res_id).exists() if tx.res_model else None
        if record and hasattr(record, '_nhcx_on_response'):
            record.with_company(tx.company_id)._nhcx_on_response(action, headers, payload, error)
        return 202, ack, None
