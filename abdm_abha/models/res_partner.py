from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .abdm_abha import format_abha_number


class ResPartner(models.Model):
    _inherit = 'res.partner'

    abha_number = fields.Char(
        string='ABHA Number', copy=False, index=True, tracking=True,
        help='14-digit Ayushman Bharat Health Account number (xx-xxxx-xxxx-xxxx).')
    abha_address = fields.Char(
        string='ABHA Address', copy=False, tracking=True,
        help='Patient health address, e.g. name@sbx (sandbox) or name@abdm.')
    abha_verified_date = fields.Datetime(string='ABHA Verified On', copy=False, readonly=True)
    abha_verified_by = fields.Many2one('res.users', string='ABHA Verified By', copy=False, readonly=True)
    abha_verification_method = fields.Selection([
        ('aadhaar_otp', 'Aadhaar OTP'),
        ('mobile_otp', 'Mobile OTP'),
        ('enrolment', 'Created with Aadhaar'),
    ], string='Verified With', copy=False, readonly=True)
    abha_kyc_verified = fields.Boolean(string='ABHA KYC Verified', copy=False, readonly=True)
    abha_account_status = fields.Char(string='ABHA Status', copy=False, readonly=True)
    abha_card = fields.Binary(string='ABHA Card', attachment=True, copy=False)
    abha_card_filename = fields.Char(copy=False)
    abha_consent_date = fields.Datetime(
        string='Aadhaar Consent On', copy=False, readonly=True,
        help='When the patient consented to share Aadhaar for ABHA creation.')
    abha_consent_by = fields.Many2one('res.users', string='Consent Recorded By', copy=False, readonly=True)

    _abha_number_uniq = models.UniqueIndex(
        '(abha_number) WHERE abha_number IS NOT NULL AND active',
        'This ABHA number is already linked to another contact.',
    )

    @api.constrains('abha_number')
    def _check_abha_number(self):
        for partner in self.filtered('abha_number'):
            if format_abha_number(partner.abha_number) != partner.abha_number:
                raise ValidationError(self.env._(
                    "ABHA number must have 14 digits in the form 91-1234-5678-9012."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('abha_number'):
                vals['abha_number'] = format_abha_number(vals['abha_number']) or vals['abha_number']
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('abha_number'):
            vals['abha_number'] = format_abha_number(vals['abha_number']) or vals['abha_number']
        if 'abha_number' in vals and not vals['abha_number']:
            # Unlinking the ABHA clears what was verified with it.
            vals.update(abha_address=False, abha_verified_date=False, abha_verified_by=False,
                        abha_verification_method=False, abha_kyc_verified=False,
                        abha_account_status=False, abha_card=False, abha_card_filename=False)
        return super().write(vals)

    # ------------------------------------------------------------------
    # Mapping ABHA profile -> contact (vertical modules extend this)
    # ------------------------------------------------------------------
    @api.model
    def _abdm_partner_vals_from_profile(self, profile, for_create=False):
        """Contact values built from a normalized ABHA profile.

        Override to map specialty fields (date of birth, gender...). Only
        non-empty values are returned so existing data is never blanked.
        """
        vals = {
            'name': profile.get('name'),
            'phone': profile.get('mobile'),
            'email': profile.get('email'),
            'street': profile.get('address'),
            'zip': profile.get('pincode'),
            'city': profile.get('district_name'),
        }
        india = self.env.ref('base.in', raise_if_not_found=False)
        if india:
            vals['country_id'] = india.id
            if profile.get('state_name'):
                state = self.env['res.country.state'].search([
                    ('country_id', '=', india.id),
                    ('name', '=ilike', profile['state_name'].strip()),
                ], limit=1)
                vals['state_id'] = state.id or False
        if profile.get('photo'):
            vals['image_1920'] = profile['photo']
        return {k: v for k, v in vals.items() if v}

    def _abdm_apply_abha_profile(self, profile, method, overwrite=True, card=None, card_ext=None,
                                 consent=False):
        """Store a verified ABHA on this contact."""
        self.ensure_one()
        if not profile.get('abha_number'):
            raise UserError(self.env._("ABDM did not return an ABHA number."))
        other = self.with_context(active_test=False).search([
            ('abha_number', '=', profile['abha_number']), ('id', '!=', self.id)], limit=1)
        if other:
            raise UserError(self.env._(
                "ABHA %(abha)s is already linked to %(name)s. Open that contact instead.",
                abha=profile['abha_number'], name=other.display_name))
        vals = {
            'abha_number': profile['abha_number'],
            'abha_address': profile.get('abha_address') or self.abha_address,
            'abha_verified_date': fields.Datetime.now(),
            'abha_verified_by': self.env.uid,
            'abha_verification_method': method,
            'abha_kyc_verified': profile.get('kyc_verified', False),
            'abha_account_status': profile.get('status') or False,
        }
        if consent:
            vals.update(abha_consent_date=fields.Datetime.now(), abha_consent_by=self.env.uid)
        if card:
            vals.update(abha_card=card,
                        abha_card_filename='ABHA-%s.%s' % (profile['abha_number'], card_ext or 'png'))
        demographic = self._abdm_partner_vals_from_profile(profile)
        if not overwrite:
            # keep what the clinic typed, only fill the gaps
            demographic = {k: v for k, v in demographic.items() if not self[k]}
        vals.update(demographic)
        self.write(vals)
        self.message_post(body=self.env._(
            "ABHA %(abha)s verified (%(method)s).", abha=profile['abha_number'],
            method=dict(self._fields['abha_verification_method'].selection).get(method)))
        return True

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_abdm_abha_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('ABHA'),
            'res_model': 'abdm.abha.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': self.id,
                        'default_mode': 'verify_number' if self.abha_number else 'start',
                        'default_abha_number': self.abha_number},
        }

    def action_abdm_abha_download_card(self):
        self.ensure_one()
        if not self.abha_card:
            raise UserError(self.env._("No ABHA card stored. Verify the ABHA again to fetch it."))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/res.partner/%s/abha_card/%s?download=true'
                   % (self.id, self.abha_card_filename or 'abha_card.png'),
            'target': 'self',
        }

    def action_abdm_abha_unlink(self):
        self.ensure_one()
        number = self.abha_number
        self.write({'abha_number': False})
        if number:
            self.message_post(body=self.env._("ABHA %s unlinked from this contact.", number))
        return True
