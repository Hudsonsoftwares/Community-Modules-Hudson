import re

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.abdm_base.models.abdm_gateway import AbdmError

from ..models.abdm_abha import digits, format_abha_number

# Shown to the patient before Aadhaar is used. During ABDM functional testing,
# compare it with the latest consent wording published by NHA.
AADHAAR_CONSENT_TEXT = """
<p>I, hereby declare that I am voluntarily sharing my Aadhaar number and demographic
information issued by UIDAI with National Health Authority (NHA) for the sole purpose
of creation of my ABHA (Ayushman Bharat Health Account) number.</p>
<p>I understand that my ABHA number can be used and shared for purposes as may be
notified by ABDM from time to time, including provision of healthcare services.
My personal identifiable information (name, address, age, date of birth, gender and
photograph) may be made available to the entities working in the National Digital
Health Ecosystem (NDHE), including health care professionals and facilities, only
with my consent.</p>
<p>I authorize NHA to use my Aadhaar number for performing Aadhaar based authentication
with UIDAI as per the provisions of the Aadhaar Act, 2016, for the aforesaid purpose.
I understand that UIDAI will share my e-KYC details or response of "Yes" with NHA upon
authentication.</p>
<p>I consciously choose to use Aadhaar number for the purpose of availing benefits across
the NDHE. I am aware that my personal identifiable information excluding Aadhaar number /
VID number can be used and shared for the purposes mentioned above. I reserve the right
to revoke the given consent at any point of time.</p>
"""

MODES = [
    ('start', 'Choose'),
    ('verify_number', 'Patient knows ABHA number'),
    ('search_mobile', 'Find ABHA by mobile number'),
    ('create_aadhaar', 'Create new ABHA with Aadhaar'),
]
STEPS = [
    ('input', 'Details'),
    ('select', 'Select account'),
    ('otp', 'Enter OTP'),
    ('mobile_otp', 'Verify mobile'),
    ('address', 'ABHA address'),
    ('done', 'Review & save'),
]
GENDERS = {'M': 'Male', 'F': 'Female', 'O': 'Other', 'T': 'Transgender', 'U': 'Undisclosed'}


class AbdmAbhaWizardAccount(models.TransientModel):
    _name = 'abdm.abha.wizard.account'
    _description = 'ABHA account found by mobile'
    _order = 'index'

    wizard_id = fields.Many2one('abdm.abha.wizard', required=True, ondelete='cascade')
    index = fields.Integer()
    abha_number = fields.Char(string='ABHA Number')
    name = fields.Char()
    gender = fields.Char()
    kyc_verified = fields.Boolean(string='KYC')

    @api.depends('name', 'abha_number')
    def _compute_display_name(self):
        for line in self:
            line.display_name = '%s  (%s)' % (line.name or '?', line.abha_number or '?')


class AbdmAbhaWizardAddress(models.TransientModel):
    _name = 'abdm.abha.wizard.address'
    _description = 'Suggested ABHA address'

    wizard_id = fields.Many2one('abdm.abha.wizard', required=True, ondelete='cascade')
    name = fields.Char(required=True)


class AbdmAbhaWizard(models.TransientModel):
    _name = 'abdm.abha.wizard'
    _description = 'ABHA Registration / Verification'

    partner_id = fields.Many2one('res.partner', string='Patient', readonly=True)
    mode = fields.Selection(MODES, default='start', required=True)
    step = fields.Selection(STEPS, default='input', required=True)
    environment = fields.Char(compute='_compute_environment')

    # inputs (Aadhaar and OTP are cleared as soon as they are used)
    abha_number = fields.Char(string='ABHA Number')
    auth_method = fields.Selection([
        ('aadhaar', 'OTP on Aadhaar-linked mobile'),
        ('mobile', 'OTP on ABHA-linked mobile'),
    ], string='Send OTP to', default='aadhaar', required=True)
    mobile = fields.Char(string='Mobile Number')
    aadhaar = fields.Char(string='Aadhaar Number')
    aadhaar_masked = fields.Char(readonly=True)
    consent_text = fields.Html(default=lambda self: AADHAAR_CONSENT_TEXT, readonly=True, sanitize=False)
    consent_given = fields.Boolean(string='Patient has read and agreed to the consent above')
    otp = fields.Char(string='OTP')
    otp_message = fields.Char(readonly=True)

    # ABDM session
    txn_id = fields.Char(readonly=True)
    x_token = fields.Char(readonly=True)
    is_new = fields.Boolean(readonly=True)
    account_ids = fields.One2many('abdm.abha.wizard.account', 'wizard_id', string='Accounts Found')
    account_id = fields.Many2one('abdm.abha.wizard.account', string='Account',
                                 domain="[('wizard_id', '=', id)]")
    address_ids = fields.One2many('abdm.abha.wizard.address', 'wizard_id', string='Address Suggestions')
    address_id = fields.Many2one('abdm.abha.wizard.address', string='Suggestions',
                                 domain="[('wizard_id', '=', id)]")
    custom_address = fields.Char(string='Or type your own')

    # verified profile
    profile = fields.Json(readonly=True)
    profile_name = fields.Char(string='Name', readonly=True)
    profile_abha_number = fields.Char(string='Verified ABHA Number', readonly=True)
    profile_abha_address = fields.Char(string='ABHA Address', readonly=True)
    profile_gender = fields.Char(string='Gender', readonly=True)
    profile_dob = fields.Date(string='Date of Birth', readonly=True)
    profile_mobile = fields.Char(string='Mobile', readonly=True)
    profile_kyc = fields.Boolean(string='KYC Verified', readonly=True)
    profile_photo = fields.Binary(string='Photo', readonly=True)
    existing_partner_id = fields.Many2one('res.partner', string='Already registered as', readonly=True)
    update_details = fields.Boolean(
        string='Update patient details from ABHA', default=True,
        help='Overwrite name, mobile, address and photo with the KYC-verified ABHA data. '
             'When off, only empty fields are filled.')
    method_used = fields.Selection([
        ('aadhaar_otp', 'Aadhaar OTP'),
        ('mobile_otp', 'Mobile OTP'),
        ('enrolment', 'Created with Aadhaar'),
    ], readonly=True)

    def _compute_environment(self):
        env_name = self.env['abdm.gateway']._get_config()['environment']
        for wiz in self:
            wiz.environment = env_name

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _api(self):
        return self.env['abdm.abha']

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('ABHA'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def _check_otp(self):
        otp = digits(self.otp)
        if len(otp) != 6:
            raise UserError(self.env._("Enter the 6-digit OTP the patient received."))
        return otp

    def _check_mobile(self, value=None):
        mobile = digits(value if value is not None else self.mobile)[-10:]
        if not re.match(r'^[6-9]\d{9}$', mobile):
            raise UserError(self.env._("Enter a valid 10-digit Indian mobile number."))
        return mobile

    def _set_profile(self, profile, method):
        stored = dict(profile, dob=profile['dob'].isoformat() if profile.get('dob') else False)
        existing = self.env['res.partner'].with_context(active_test=False).search(
            [('abha_number', '=', profile.get('abha_number'))], limit=1) if profile.get('abha_number') else False
        if existing and self.partner_id and existing == self.partner_id:
            existing = False
        self.write({
            'profile': stored,
            'profile_name': profile.get('name'),
            'profile_abha_number': profile.get('abha_number'),
            'profile_abha_address': profile.get('abha_address'),
            'profile_gender': GENDERS.get(profile.get('gender') or '', profile.get('gender')),
            'profile_dob': profile.get('dob') or False,
            'profile_mobile': profile.get('mobile'),
            'profile_kyc': profile.get('kyc_verified'),
            'profile_photo': profile.get('photo') or False,
            'existing_partner_id': existing.id if existing else False,
            'method_used': method,
            'otp': False,
        })

    def _profile_dict(self):
        profile = dict(self.profile or {})
        if profile.get('dob'):
            profile['dob'] = fields.Date.to_date(profile['dob'])
        return profile

    # ------------------------------------------------------------------
    # step 0: choose a path
    # ------------------------------------------------------------------
    def action_choose_verify(self):
        self.write({'mode': 'verify_number', 'step': 'input'})
        return self._reopen()

    def action_choose_search(self):
        self.write({'mode': 'search_mobile', 'step': 'input', 'auth_method': 'mobile'})
        return self._reopen()

    def action_choose_create(self):
        self.write({'mode': 'create_aadhaar', 'step': 'input'})
        return self._reopen()

    def action_back(self):
        self.write({'mode': 'start', 'step': 'input', 'otp': False, 'txn_id': False,
                    'otp_message': False, 'aadhaar': False, 'aadhaar_masked': False})
        self.account_ids.unlink()
        self.address_ids.unlink()
        return self._reopen()

    # ------------------------------------------------------------------
    # verify an existing ABHA (by number, or by mobile search)
    # ------------------------------------------------------------------
    def action_search_mobile(self):
        mobile = self._check_mobile()
        txn_id, accounts = self._api().search_by_mobile(mobile)
        if not accounts:
            raise UserError(self.env._(
                "No ABHA found for this mobile number. Try the ABHA number, or create a new ABHA."))
        self.account_ids.unlink()
        lines = self.env['abdm.abha.wizard.account'].create([{
            'wizard_id': self.id,
            'index': int(acc.get('index') or 0),
            'abha_number': acc.get('ABHANumber') or acc.get('abhaNumber'),
            'name': acc.get('name'),
            'gender': GENDERS.get((acc.get('gender') or '').upper()[:1], acc.get('gender')),
            'kyc_verified': str(acc.get('kycVerified')).lower() == 'true',
        } for acc in accounts])
        self.write({'txn_id': txn_id, 'step': 'select', 'account_id': lines[:1].id})
        return self._reopen()

    def action_send_login_otp(self):
        if self.mode == 'search_mobile':
            if not self.account_id:
                raise UserError(self.env._("Select the patient's ABHA account."))
            txn_id, message = self._api().login_request_otp(
                'index', str(self.account_id.index), self.auth_method, txn_id=self.txn_id)
        else:
            number = format_abha_number(self.abha_number)
            if not number:
                raise UserError(self.env._("ABHA number must have 14 digits (e.g. 91-1234-5678-9012)."))
            self.abha_number = number
            try:
                txn_id, message = self._api().login_request_otp('abha-number', number, self.auth_method)
            except AbdmError as e:
                if '1114' not in str(e.code or ''):
                    raise
                env_name = self.env['abdm.gateway']._get_config()['environment']
                raise UserError(self.env._(
                    "ABDM has no ABHA account with the number %(number)s (%(env)s environment).\n\n"
                    "- Check the number on the patient's ABHA card.\n"
                    "- An ABHA created on another environment (e.g. the live ABHA app while "
                    "Odoo is on sandbox) does not exist here.\n"
                    "- Or go back and choose \"Yes, but only remembers the mobile number\", or create a new ABHA.",
                    number=number, env=env_name)) from e
        self.write({'txn_id': txn_id, 'otp_message': message, 'step': 'otp', 'otp': False})
        return self._reopen()

    def action_verify_login_otp(self):
        otp = self._check_otp()
        x_token = self._api().login_verify_otp(self.txn_id, otp, self.auth_method)
        profile = self._api().get_profile(x_token)
        self.write({'x_token': x_token, 'step': 'done'})
        self._set_profile(profile, 'aadhaar_otp' if self.auth_method == 'aadhaar' else 'mobile_otp')
        return self._reopen()

    # ------------------------------------------------------------------
    # create a new ABHA with Aadhaar
    # ------------------------------------------------------------------
    def action_enrol_send_otp(self):
        if not self.consent_given:
            raise UserError(self.env._("Read the consent to the patient and tick the box first."))
        aadhaar = digits(self.aadhaar)
        if len(aadhaar) != 12:
            raise UserError(self.env._("Aadhaar number must have 12 digits."))
        txn_id, message = self._api().enrol_request_aadhaar_otp(aadhaar)
        # never keep the Aadhaar number
        self.write({'txn_id': txn_id, 'otp_message': message, 'step': 'otp', 'otp': False,
                    'aadhaar': False, 'aadhaar_masked': 'XXXX-XXXX-%s' % aadhaar[-4:]})
        return self._reopen()

    def action_enrol_verify_otp(self):
        otp = self._check_otp()
        mobile = self._check_mobile()
        txn_id, x_token, profile, is_new = self._api().enrol_by_aadhaar(self.txn_id, otp, mobile)
        self.write({'txn_id': txn_id, 'x_token': x_token, 'is_new': is_new})
        self._set_profile(profile, 'enrolment')
        if profile.get('mobile') != mobile:
            # The mobile given is not the Aadhaar-linked one: ABDM wants it verified.
            txn_id, message = self._api().enrol_request_mobile_otp(self.txn_id, mobile)
            self.write({'txn_id': txn_id, 'otp_message': message, 'step': 'mobile_otp'})
            return self._reopen()
        return self._go_to_address_step()

    def action_enrol_verify_mobile(self):
        otp = self._check_otp()
        txn_id = self._api().enrol_verify_mobile(self.txn_id, otp)
        profile = self._profile_dict()
        profile['mobile'] = self._check_mobile()
        self.write({'txn_id': txn_id})
        self._set_profile(profile, 'enrolment')
        return self._go_to_address_step()

    def action_skip_mobile(self):
        return self._go_to_address_step()

    def action_resend_mobile_otp(self):
        txn_id, message = self._api().enrol_request_mobile_otp(self.txn_id, self._check_mobile())
        self.write({'txn_id': txn_id, 'otp_message': message, 'otp': False})
        return self._reopen()

    def _go_to_address_step(self):
        if self.profile_abha_address and not self.is_new:
            # existing ABHA already has an address
            self.step = 'done'
            return self._reopen()
        try:
            suggestions = self._api().enrol_address_suggestions(self.txn_id)
        except UserError:
            suggestions = []
        self.address_ids.unlink()
        lines = self.env['abdm.abha.wizard.address'].create(
            [{'wizard_id': self.id, 'name': s} for s in suggestions[:8]])
        self.write({'step': 'address', 'address_id': lines[:1].id, 'otp': False})
        return self._reopen()

    def action_set_address(self):
        address = (self.custom_address or (self.address_id.name if self.address_id else '') or '').strip()
        if not address:
            raise UserError(self.env._("Choose a suggested ABHA address or type one."))
        if '@' in address:
            address = address.split('@', 1)[0]
        if not re.match(r'^[A-Za-z0-9._]{4,32}$', address):
            raise UserError(self.env._(
                "ABHA address may use letters, numbers, dot and underscore (4 to 32 characters)."))
        saved = self._api().enrol_set_abha_address(self.txn_id, address)
        profile = self._profile_dict()
        profile['abha_address'] = saved
        self._set_profile(profile, 'enrolment')
        self.step = 'done'
        return self._reopen()

    def action_skip_address(self):
        self.step = 'done'
        return self._reopen()

    def action_resend_otp(self):
        if self.mode == 'create_aadhaar':
            raise UserError(self.env._(
                "To get a new Aadhaar OTP, go back and enter the Aadhaar number again."))
        return self.action_send_login_otp()

    # ------------------------------------------------------------------
    # final step: store on the patient
    # ------------------------------------------------------------------
    def _target_partner(self):
        """The contact to update, or an empty recordset when one must be created."""
        if self.partner_id:
            return self.partner_id
        return self.existing_partner_id

    def action_link_partner(self):
        self.ensure_one()
        profile = self._profile_dict()
        if not profile.get('abha_number'):
            raise UserError(self.env._("Nothing verified yet."))
        if self.partner_id and self.existing_partner_id:
            raise UserError(self.env._(
                "This ABHA already belongs to %s. Open that patient instead, or unlink the ABHA there first.",
                self.existing_partner_id.display_name))
        card, card_ext = False, False
        if self.x_token:
            try:
                card, card_ext = self._api().get_card(self.x_token)
            except UserError:
                card = False  # the card is a convenience; never block the link for it
        Partner = self.env['res.partner']
        partner = self._target_partner()
        overwrite = self.update_details
        if not partner:
            partner = Partner.create(Partner._abdm_partner_vals_from_profile(profile, for_create=True)
                                     or {'name': profile.get('name') or profile['abha_number']})
            overwrite = True
        partner._abdm_apply_abha_profile(
            profile, self.method_used or 'aadhaar_otp', overwrite=overwrite,
            card=card, card_ext=card_ext, consent=self.mode == 'create_aadhaar')
        self.write({'x_token': False, 'txn_id': False})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': partner.id,
            'view_mode': 'form',
            'target': 'current',
        }
