"""ABHA V3 API calls (enrolment with Aadhaar, login/verification, profile).

Endpoints were checked against the sandbox (abhasbx.abdm.gov.in) on
2026-11-11. Every sensitive value (Aadhaar, OTP, login IDs) is RSA-encrypted
with the ABHA public key before it leaves Odoo (abdm.gateway.abha_encrypt).
"""
import base64
import re
from datetime import date

from odoo import api, models
from odoo.exceptions import UserError
from odoo.tools.image import binary_to_image

# Enrolment
PATH_ENROL_REQUEST_OTP = '/v3/enrollment/request/otp'
PATH_ENROL_BY_AADHAAR = '/v3/enrollment/enrol/byAadhaar'
PATH_ENROL_AUTH_BY_ABDM = '/v3/enrollment/auth/byAbdm'
PATH_ENROL_ADDRESS_SUGGESTION = '/v3/enrollment/enrol/suggestion'
PATH_ENROL_ABHA_ADDRESS = '/v3/enrollment/enrol/abha-address'
# Login / verification
PATH_LOGIN_REQUEST_OTP = '/v3/profile/login/request/otp'
PATH_LOGIN_VERIFY = '/v3/profile/login/verify'
PATH_SEARCH_ABHA = '/v3/profile/account/abha/search'
PATH_PROFILE = '/v3/profile/account'
PATH_ABHA_CARD = '/v3/profile/account/abha-card'

ENROLMENT_CONSENT = {'code': 'abha-enrollment', 'version': '1.4'}


def digits(value):
    return re.sub(r'\D', '', value or '')


def format_abha_number(value):
    """'91123456789012' or '91-1234-5678-9012' -> '91-1234-5678-9012'."""
    d = digits(value)
    if len(d) != 14:
        return False
    return '%s-%s-%s-%s' % (d[:2], d[2:6], d[6:10], d[10:])


def _get(data, *names):
    """First non-empty value among ``names``, case-insensitive."""
    if not isinstance(data, dict):
        return None
    lowered = {str(k).lower(): v for k, v in data.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value not in (None, '', [], {}):
            return value
    return None


def _parse_date(value):
    if not value or not isinstance(value, str):
        return None
    for pattern, order in ((r'^(\d{1,2})-(\d{1,2})-(\d{4})$', 'dmy'),
                           (r'^(\d{1,2})/(\d{1,2})/(\d{4})$', 'dmy'),
                           (r'^(\d{4})-(\d{1,2})-(\d{1,2})', 'ymd')):
        m = re.match(pattern, value.strip())
        if m:
            a, b, c = (int(x) for x in m.groups())
            try:
                return date(c, b, a) if order == 'dmy' else date(a, b, c)
            except ValueError:
                return None
    return None


def normalize_profile(data):
    """Turn the different ABHA profile shapes into one flat dict."""
    if not isinstance(data, dict):
        return {}
    first = _get(data, 'firstName') or ''
    middle = _get(data, 'middleName') or ''
    last = _get(data, 'lastName') or ''
    name = _get(data, 'name', 'fullName') or ' '.join(p for p in (first, middle, last) if p)

    dob = _parse_date(_get(data, 'dob', 'dateOfBirth'))
    year = _get(data, 'yearOfBirth')
    if not dob and year:
        try:
            dob = date(int(year), int(_get(data, 'monthOfBirth') or 1), int(_get(data, 'dayOfBirth') or 1))
        except (TypeError, ValueError):
            dob = None

    address = _get(data, 'preferredAbhaAddress', 'abhaAddress', 'healthId')
    phr = _get(data, 'phrAddress')
    if not address and isinstance(phr, list) and phr:
        address = phr[0]

    kyc = _get(data, 'kycVerified', 'kycverified')
    if isinstance(kyc, str):
        kyc = kyc.lower() == 'true'
    verification = (_get(data, 'verificationStatus') or '')
    if kyc is None and verification:
        kyc = verification.upper() == 'VERIFIED'

    photo = _get(data, 'photo', 'profilePhoto', 'kycPhoto')
    if photo and isinstance(photo, str) and ',' in photo[:40]:
        photo = photo.split(',', 1)[1]  # strip data:image/...;base64,
    if photo:
        try:
            binary_to_image(base64.b64decode(photo)).verify()
        except Exception:  # noqa: BLE001 - a broken photo must never block registration
            photo = None

    return {
        'abha_number': format_abha_number(_get(data, 'ABHANumber', 'abhaNumber', 'healthIdNumber')),
        'abha_address': address or False,
        'name': (name or '').strip(),
        'gender': (_get(data, 'gender') or '').upper()[:1] or False,
        'dob': dob,
        'mobile': digits(_get(data, 'mobile', 'mobileNumber'))[-10:] or False,
        'email': _get(data, 'email') or False,
        'address': _get(data, 'address') or False,
        'pincode': _get(data, 'pinCode', 'pincode') or False,
        'district_name': _get(data, 'districtName') or False,
        'state_name': _get(data, 'stateName') or False,
        'photo': photo or False,
        'status': _get(data, 'abhaStatus', 'status') or False,
        'abha_type': _get(data, 'abhaType') or False,
        'kyc_verified': bool(kyc),
    }


class AbdmAbha(models.AbstractModel):
    _name = 'abdm.abha'
    _description = 'ABHA API'

    @api.model
    def _gw(self):
        return self.env['abdm.gateway']

    @api.model
    def _post(self, path, payload, headers=None):
        return self._gw()._request('POST', path, payload, service='abha', headers=headers)['data'] or {}

    @api.model
    def _otp_block(self, txn_id, otp):
        return {'authMethods': ['otp'], 'otp': {
            'timeStamp': self._gw()._timestamp(),
            'txnId': txn_id,
            'otpValue': self._gw().abha_encrypt(otp),
        }}

    @staticmethod
    def _txn(data):
        txn = _get(data, 'txnId')
        if not txn:
            raise UserError("ABDM did not return a transaction ID. Please try again.")
        return txn

    # ------------------------------------------------------------------
    # Enrolment (new ABHA with Aadhaar)
    # ------------------------------------------------------------------
    @api.model
    def enrol_request_aadhaar_otp(self, aadhaar):
        data = self._post(PATH_ENROL_REQUEST_OTP, {
            'txnId': '',
            'scope': ['abha-enrol'],
            'loginHint': 'aadhaar',
            'loginId': self._gw().abha_encrypt(aadhaar),
            'otpSystem': 'aadhaar',
        })
        return self._txn(data), _get(data, 'message') or ''

    @api.model
    def enrol_by_aadhaar(self, txn_id, otp, mobile):
        """Returns (txn_id, x_token, normalized profile, is_new)."""
        auth = self._otp_block(txn_id, otp)
        auth['otp']['mobile'] = mobile
        data = self._post(PATH_ENROL_BY_AADHAAR, {'authData': auth, 'consent': ENROLMENT_CONSENT})
        tokens = _get(data, 'tokens') or {}
        profile = normalize_profile(_get(data, 'ABHAProfile') or {})
        is_new = _get(data, 'isNew')
        return _get(data, 'txnId') or txn_id, _get(tokens, 'token'), profile, bool(is_new)

    @api.model
    def enrol_request_mobile_otp(self, txn_id, mobile):
        data = self._post(PATH_ENROL_REQUEST_OTP, {
            'txnId': txn_id,
            'scope': ['abha-enrol', 'mobile-verify'],
            'loginHint': 'mobile',
            'loginId': self._gw().abha_encrypt(mobile),
            'otpSystem': 'abdm',
        })
        return _get(data, 'txnId') or txn_id, _get(data, 'message') or ''

    @api.model
    def enrol_verify_mobile(self, txn_id, otp):
        data = self._post(PATH_ENROL_AUTH_BY_ABDM, {
            'scope': ['abha-enrol', 'mobile-verify'],
            'authData': self._otp_block(txn_id, otp),
        })
        status = (_get(data, 'authResult') or '').lower()
        if status and status != 'success':
            raise UserError(_get(data, 'message') or "Mobile verification failed.")
        return _get(data, 'txnId') or txn_id

    @api.model
    def enrol_address_suggestions(self, txn_id):
        data = self._gw()._request('GET', PATH_ENROL_ADDRESS_SUGGESTION, service='abha',
                                   headers={'Transaction_Id': txn_id})['data'] or {}
        return _get(data, 'abhaAddressList') or []

    @api.model
    def enrol_set_abha_address(self, txn_id, address):
        data = self._post(PATH_ENROL_ABHA_ADDRESS, {
            'txnId': txn_id, 'abhaAddress': address, 'preferred': 1,
        })
        return _get(data, 'preferredAbhaAddress') or address

    # ------------------------------------------------------------------
    # Verification of an existing ABHA (login)
    # ------------------------------------------------------------------
    @api.model
    def _login_scope(self, method):
        return ['abha-login', 'aadhaar-verify' if method == 'aadhaar' else 'mobile-verify']

    @api.model
    def login_request_otp(self, login_hint, login_id, method, txn_id=None):
        """login_hint: 'abha-number' or 'index' (after a mobile search)."""
        payload = {
            'scope': self._login_scope(method),
            'loginHint': login_hint,
            'loginId': self._gw().abha_encrypt(login_id),
            'otpSystem': 'aadhaar' if method == 'aadhaar' else 'abdm',
        }
        if txn_id:
            payload['txnId'] = txn_id
        data = self._post(PATH_LOGIN_REQUEST_OTP, payload)
        return self._txn(data), _get(data, 'message') or ''

    @api.model
    def login_verify_otp(self, txn_id, otp, method):
        """Returns the X-token of the verified ABHA account."""
        data = self._post(PATH_LOGIN_VERIFY, {
            'scope': self._login_scope(method),
            'authData': self._otp_block(txn_id, otp),
        })
        status = (_get(data, 'authResult') or '').lower()
        token = _get(data, 'token')
        if (status and status != 'success') or not token:
            raise UserError(_get(data, 'message') or "OTP verification failed. Check the OTP and try again.")
        return token

    @api.model
    def search_by_mobile(self, mobile):
        """Returns (txn_id, [account dicts with index, ABHANumber, name, gender])."""
        data = self._gw()._request('POST', PATH_SEARCH_ABHA, {
            'scope': ['search-abha'],
            'mobile': self._gw().abha_encrypt(mobile),
        }, service='abha')['data']
        entries = data if isinstance(data, list) else [data] if data else []
        txn_id, accounts = False, []
        for entry in entries:
            txn_id = txn_id or _get(entry, 'txnId')
            accounts.extend(_get(entry, 'ABHA') or [])
        return txn_id, accounts

    # ------------------------------------------------------------------
    # Profile and card of a verified account
    # ------------------------------------------------------------------
    @api.model
    def _x_token_headers(self, x_token):
        return {'X-token': 'Bearer %s' % x_token}

    @api.model
    def get_profile(self, x_token):
        data = self._gw()._request('GET', PATH_PROFILE, service='abha',
                                   headers=self._x_token_headers(x_token))['data']
        return normalize_profile(data)

    @api.model
    def get_card(self, x_token):
        """Returns (base64 content, file extension) of the ABHA card, or (False, False)."""
        content = self._gw()._request('GET', PATH_ABHA_CARD, service='abha', raw=True,
                                      headers=self._x_token_headers(x_token))['data']
        if not isinstance(content, (bytes, bytearray)) or not content:
            return False, False
        if content[:4] == b'%PDF':
            ext = 'pdf'
        elif content[:3] == b'\xff\xd8\xff':
            ext = 'jpg'
        else:
            ext = 'png'
        return base64.b64encode(content).decode(), ext
