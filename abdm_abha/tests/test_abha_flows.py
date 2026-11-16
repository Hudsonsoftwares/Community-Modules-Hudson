import base64
from datetime import date

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.abdm_base.tests.common import AbdmTestMixin, FakeResponse
from odoo.addons.abdm_abha.models.abdm_abha import format_abha_number, normalize_profile

# 1x1 transparent PNG
PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')

LOGIN_PROFILE = {
    'ABHANumber': '91-1111-2222-3333',
    'preferredAbhaAddress': 'ravi.kumar@sbx',
    'firstName': 'Ravi', 'middleName': '', 'lastName': 'Kumar', 'name': 'Ravi Kumar',
    'yearOfBirth': '1990', 'monthOfBirth': '5', 'dayOfBirth': '17',
    'gender': 'M', 'mobile': '9876543210', 'email': 'ravi@example.com',
    'address': '12 MG Road', 'pincode': '600001', 'stateName': 'TAMIL NADU',
    'districtName': 'Chennai', 'kycVerified': 'true', 'status': 'ACTIVE',
    'profilePhoto': base64.b64encode(PNG).decode(),
}
ENROL_PROFILE = {
    'firstName': 'Anita', 'lastName': 'Sharma', 'dob': '03-02-1985', 'gender': 'F',
    'mobile': None, 'phrAddress': [], 'pinCode': '110001', 'stateName': 'DELHI',
    'ABHANumber': '91-4444-5555-6666', 'abhaStatus': 'ACTIVE', 'abhaType': 'STANDARD',
}


@tagged('post_install', '-at_install', 'abdm')
class TestAbhaFlows(AbdmTestMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_abdm()
        cls.abha_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.abha_public_b64 = base64.b64encode(cls.abha_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        cls.Wizard = cls.env['abdm.abha.wizard']

    def decrypt(self, value):
        return self.abha_key.decrypt(base64.b64decode(value), padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA1()), algorithm=hashes.SHA1(), label=None)).decode()

    def fake(self, routes):
        routes = dict(routes)
        routes[('GET', '/v3/profile/public/certificate')] = FakeResponse(
            200, {'publicKey': self.abha_public_b64, 'encryptionAlgorithm': 'RSA/ECB/OAEPWithSHA-1AndMGF1Padding'})
        self.fake_abdm(routes)

    def last_call(self, suffix):
        return [c for c in self.calls if c['url'].endswith(suffix)][-1]

    def login_routes(self):
        return {
            ('POST', '/v3/profile/login/request/otp'): FakeResponse(
                200, {'txnId': 'txn-login', 'message': 'OTP sent to mobile ending 3210'}),
            ('POST', '/v3/profile/login/verify'): FakeResponse(
                200, {'txnId': 'txn-login', 'authResult': 'success', 'token': 'x-token-1', 'accounts': []}),
            ('GET', '/v3/profile/account'): FakeResponse(200, LOGIN_PROFILE),
            ('GET', '/v3/profile/account/abha-card'): FakeResponse(
                200, PNG, headers={'Content-Type': 'image/png'}),
        }

    # ------------------------------------------------------------------
    def test_helpers(self):
        self.assertEqual(format_abha_number('91111122223333'), '91-1111-2222-3333')
        self.assertFalse(format_abha_number('12345'))
        login = normalize_profile(LOGIN_PROFILE)
        self.assertEqual(login['dob'], date(1990, 5, 17))
        self.assertEqual(login['abha_address'], 'ravi.kumar@sbx')
        self.assertTrue(login['kyc_verified'])
        self.assertTrue(login['photo'])
        self.assertFalse(normalize_profile(dict(LOGIN_PROFILE, profilePhoto='bm90IGFuIGltYWdl'))['photo'],
                         'a broken photo is dropped')
        enrol = normalize_profile(ENROL_PROFILE)
        self.assertEqual(enrol['name'], 'Anita Sharma')
        self.assertEqual(enrol['dob'], date(1985, 2, 3))
        self.assertFalse(enrol['mobile'])
        self.assertEqual(enrol['abha_number'], '91-4444-5555-6666')

    def test_verify_by_number_creates_patient(self):
        self.fake(self.login_routes())
        wiz = self.Wizard.create({})
        wiz.action_choose_verify()
        wiz.write({'abha_number': '91 1111 2222 3333', 'auth_method': 'aadhaar'})
        wiz.action_send_login_otp()
        self.assertEqual(wiz.step, 'otp')
        self.assertIn('3210', wiz.otp_message)
        req = self.last_call('/v3/profile/login/request/otp')['json']
        self.assertEqual(req['scope'], ['abha-login', 'aadhaar-verify'])
        self.assertEqual(req['otpSystem'], 'aadhaar')
        self.assertEqual(req['loginHint'], 'abha-number')
        self.assertEqual(self.decrypt(req['loginId']), '91-1111-2222-3333')

        with self.assertRaises(UserError):
            wiz.otp = '12'
            wiz.action_verify_login_otp()
        wiz.otp = '123456'
        wiz.action_verify_login_otp()
        verify = self.last_call('/v3/profile/login/verify')['json']
        self.assertEqual(self.decrypt(verify['authData']['otp']['otpValue']), '123456')
        self.assertEqual(self.last_call('/v3/profile/account')['headers']['X-token'], 'Bearer x-token-1')
        self.assertEqual(wiz.step, 'done')
        self.assertFalse(wiz.otp, 'OTP must not be kept')
        self.assertEqual(wiz.profile_name, 'Ravi Kumar')

        action = wiz.action_link_partner()
        partner = self.env['res.partner'].browse(action['res_id'])
        self.assertEqual(partner.abha_number, '91-1111-2222-3333')
        self.assertEqual(partner.abha_address, 'ravi.kumar@sbx')
        self.assertEqual(partner.name, 'Ravi Kumar')
        self.assertEqual(partner.phone, '9876543210')
        self.assertEqual(partner.zip, '600001')
        self.assertEqual(partner.country_id, self.env.ref('base.in'))
        self.assertTrue(partner.abha_kyc_verified)
        self.assertEqual(partner.abha_verification_method, 'aadhaar_otp')
        self.assertTrue(partner.abha_card)
        self.assertEqual(partner.abha_card_filename, 'ABHA-91-1111-2222-3333.png')
        self.assertFalse(wiz.x_token, 'X-token must be cleared after use')

        # The same ABHA again from reception opens the existing patient.
        wiz2 = self.Wizard.create({'mode': 'verify_number', 'abha_number': '91-1111-2222-3333'})
        wiz2.action_send_login_otp()
        wiz2.otp = '654321'
        wiz2.action_verify_login_otp()
        self.assertEqual(wiz2.existing_partner_id, partner)
        action2 = wiz2.action_link_partner()
        self.assertEqual(action2['res_id'], partner.id)
        self.assertEqual(self.env['res.partner'].search_count([('abha_number', '=', '91-1111-2222-3333')]), 1)

    def test_unknown_abha_number_message(self):
        routes = self.login_routes()
        routes[('POST', '/v3/profile/login/request/otp')] = FakeResponse(
            400, {'error': {'code': 'ABDM-1114', 'message': 'ABHA number not found'}})
        self.fake(routes)
        wiz = self.Wizard.create({'mode': 'verify_number', 'abha_number': '75-7146-3686-5863'})
        with self.assertRaisesRegex(UserError, 'another environment'):
            wiz.action_send_login_otp()

    def test_search_by_mobile_updates_existing_contact(self):
        routes = self.login_routes()
        routes[('POST', '/v3/profile/account/abha/search')] = FakeResponse(200, [{
            'txnId': 'txn-search',
            'ABHA': [{'index': 1, 'ABHANumber': 'xx-xxxx-xxxx-3333', 'name': 'Ravi Kumar', 'gender': 'M'},
                     {'index': 2, 'ABHANumber': 'xx-xxxx-xxxx-9999', 'name': 'Meena Kumar', 'gender': 'F'}],
        }])
        self.fake(routes)
        partner = self.env['res.partner'].create({'name': 'R. Kumar (typed at desk)', 'phone': '044-1234'})
        wiz = self.Wizard.with_context(**partner.action_abdm_abha_wizard()['context']).create({})
        self.assertEqual(wiz.partner_id, partner)
        wiz.action_choose_search()
        wiz.mobile = '98765 43210'
        wiz.action_search_mobile()
        self.assertEqual(wiz.step, 'select')
        self.assertEqual(len(wiz.account_ids), 2)
        self.assertEqual(self.decrypt(self.last_call('/abha/search')['json']['mobile']), '9876543210')
        wiz.account_id = wiz.account_ids.filtered(lambda a: a.index == 1)
        wiz.action_send_login_otp()
        req = self.last_call('/v3/profile/login/request/otp')['json']
        self.assertEqual(req['loginHint'], 'index')
        self.assertEqual(self.decrypt(req['loginId']), '1')
        self.assertEqual(req['txnId'], 'txn-search')
        self.assertEqual(req['scope'], ['abha-login', 'mobile-verify'])
        self.assertEqual(req['otpSystem'], 'abdm')
        wiz.otp = '111111'
        wiz.action_verify_login_otp()
        wiz.update_details = False
        wiz.action_link_partner()
        self.assertEqual(partner.abha_number, '91-1111-2222-3333')
        self.assertEqual(partner.name, 'R. Kumar (typed at desk)', 'name kept when not updating')
        self.assertEqual(partner.phone, '044-1234')
        self.assertEqual(partner.zip, '600001', 'empty fields are still filled')
        self.assertEqual(partner.abha_verification_method, 'mobile_otp')

    def test_create_with_aadhaar(self):
        self.fake({
            ('POST', '/v3/enrollment/request/otp'): [
                FakeResponse(200, {'txnId': 'txn-enrol', 'message': 'OTP sent to Aadhaar mobile ******0000'}),
                FakeResponse(200, {'txnId': 'txn-enrol', 'message': 'OTP sent to 9123456789'}),
            ],
            ('POST', '/v3/enrollment/enrol/byAadhaar'): FakeResponse(200, {
                'txnId': 'txn-enrol', 'message': 'Account created',
                'tokens': {'token': 'x-token-new', 'expiresIn': 1800},
                'ABHAProfile': ENROL_PROFILE, 'isNew': True}),
            ('POST', '/v3/enrollment/auth/byAbdm'): FakeResponse(200, {
                'txnId': 'txn-enrol', 'authResult': 'success', 'message': 'Mobile verified'}),
            ('GET', '/v3/enrollment/enrol/suggestion'): FakeResponse(200, {
                'txnId': 'txn-enrol', 'abhaAddressList': ['anita.sharma', 'anita1985']}),
            ('POST', '/v3/enrollment/enrol/abha-address'): FakeResponse(200, {
                'txnId': 'txn-enrol', 'healthIdNumber': '91-4444-5555-6666',
                'preferredAbhaAddress': 'anita1985@sbx'}),
            ('GET', '/v3/profile/account/abha-card'): FakeResponse(200, b'%PDF-1.4 card'),
        })
        wiz = self.Wizard.create({})
        wiz.action_choose_create()
        wiz.aadhaar = '1234 5678 9012'
        with self.assertRaises(UserError):
            wiz.action_enrol_send_otp()  # consent not given
        wiz.consent_given = True
        wiz.action_enrol_send_otp()
        req = self.calls[-1]['json']
        self.assertEqual(req['scope'], ['abha-enrol'])
        self.assertEqual(self.decrypt(req['loginId']), '123456789012')
        self.assertFalse(wiz.aadhaar, 'Aadhaar must not be kept')
        self.assertEqual(wiz.aadhaar_masked, 'XXXX-XXXX-9012')
        log_text = ' '.join(filter(None, self.env['abdm.api.log'].search([]).mapped('request_body')))
        self.assertNotIn('123456789012', log_text)

        wiz.write({'otp': '222222', 'mobile': '9123456789'})
        wiz.action_enrol_verify_otp()
        enrol = self.last_call('/enrollment/enrol/byAadhaar')['json']
        self.assertEqual(enrol['consent'], {'code': 'abha-enrollment', 'version': '1.4'})
        self.assertEqual(enrol['authData']['otp']['mobile'], '9123456789')
        self.assertEqual(wiz.step, 'mobile_otp', 'non-Aadhaar mobile must be verified')

        wiz.otp = '333333'
        wiz.action_enrol_verify_mobile()
        self.assertEqual(wiz.step, 'address')
        self.assertEqual(wiz.address_ids.mapped('name'), ['anita.sharma', 'anita1985'])
        self.assertEqual(self.last_call('/enrol/suggestion')['headers']['Transaction_Id'], 'txn-enrol')
        wiz.custom_address = 'bad address!'
        with self.assertRaises(UserError):
            wiz.action_set_address()
        wiz.custom_address = False
        wiz.address_id = wiz.address_ids.filtered(lambda a: a.name == 'anita1985')
        wiz.action_set_address()
        self.assertEqual(wiz.step, 'done')
        self.assertEqual(wiz.profile_abha_address, 'anita1985@sbx')

        partner = self.env['res.partner'].browse(wiz.action_link_partner()['res_id'])
        self.assertEqual(partner.name, 'Anita Sharma')
        self.assertEqual(partner.abha_number, '91-4444-5555-6666')
        self.assertEqual(partner.phone, '9123456789')
        self.assertEqual(partner.abha_verification_method, 'enrolment')
        self.assertTrue(partner.abha_consent_date)
        self.assertEqual(partner.abha_consent_by, self.env.user)
        self.assertEqual(partner.abha_card_filename, 'ABHA-91-4444-5555-6666.pdf')

    def test_abha_belongs_to_one_contact(self):
        self.fake(self.login_routes())
        self.env['res.partner'].create({'name': 'First', 'abha_number': '91-1111-2222-3333'})
        other = self.env['res.partner'].create({'name': 'Second'})
        wiz = self.Wizard.create({'partner_id': other.id, 'mode': 'verify_number',
                                  'abha_number': '91-1111-2222-3333'})
        wiz.action_send_login_otp()
        wiz.otp = '123456'
        wiz.action_verify_login_otp()
        self.assertTrue(wiz.existing_partner_id)
        with self.assertRaises(UserError):
            wiz.action_link_partner()
        with self.assertRaises(ValidationError):
            other.abha_number = '12-34'

    def test_abdm_error_is_readable(self):
        routes = self.login_routes()
        routes[('POST', '/v3/profile/login/verify')] = FakeResponse(
            400, {'code': 'ABDM-1204', 'message': 'Invalid OTP value'})
        self.fake(routes)
        wiz = self.Wizard.create({'mode': 'verify_number', 'abha_number': '91-1111-2222-3333'})
        wiz.action_send_login_otp()
        wiz.otp = '000000'
        with self.assertRaisesRegex(UserError, 'Invalid OTP value'):
            wiz.action_verify_login_otp()

    def test_unlink(self):
        partner = self.env['res.partner'].create({
            'name': 'P', 'abha_number': '91-1111-2222-3333', 'abha_address': 'p@sbx'})
        partner.action_abdm_abha_unlink()
        self.assertFalse(partner.abha_number)
        self.assertFalse(partner.abha_address)
