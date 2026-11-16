import re

from odoo import api, fields, models


def _digits(value):
    return re.sub(r'\D', '', value or '')


class ResPartner(models.Model):
    _inherit = 'res.partner'

    abdm_care_context_ids = fields.One2many('abdm.care.context', 'partner_id', string='ABDM Care Contexts')

    # --- hooks for specialty modules ------------------------------------
    def _abdm_patient_reference(self):
        """Stable patient reference shared with ABDM (never the database id
        of another facility's record)."""
        self.ensure_one()
        return self.ref or 'P-%s' % self.id

    def _abdm_demographics(self):
        """dict(name, gender 'M'/'F'/'O', year_of_birth) used by ABDM matching."""
        self.ensure_one()
        return {'name': self.name, 'gender': 'O', 'year_of_birth': False}

    def _abdm_care_context_sources(self, company=None):
        """Records of this patient that can become care contexts (e.g. dental
        cases). Specialty modules return a recordset inheriting
        ``abdm.care.context.mixin``; used when the patient discovers the
        facility from the ABHA app."""
        self.ensure_one()
        return []

    # --- discovery ------------------------------------------------------
    @api.model
    def _abdm_find_patient(self, patient):
        """Find the contact matching an ABDM discovery request.

        Strong match: verified ABHA number or ABHA address. Fallback: verified
        mobile + same gender + same year of birth + same first name.
        Returns (partner, matched_by list).
        """
        verified = {i.get('type'): i.get('value') for i in patient.get('verifiedIdentifiers') or []}
        abha_number = verified.get('ABHA_NUMBER') or verified.get('NDHM_HEALTH_NUMBER')
        Partner = self.sudo()
        if abha_number:
            digits = _digits(abha_number)
            if len(digits) == 14:
                formatted = '%s-%s-%s-%s' % (digits[:2], digits[2:6], digits[6:10], digits[10:])
                found = Partner.search([('abha_number', '=', formatted)], limit=1)
                if found:
                    return found, ['ABHA_NUMBER']
        address = patient.get('id') or verified.get('HEALTH_ID') or verified.get('ABHA_ADDRESS')
        if address:
            found = Partner.search([('abha_address', '=ilike', address)], limit=1)
            if found:
                return found, ['ABHA_ADDRESS']
        mobile = _digits(verified.get('MOBILE'))[-10:]
        if len(mobile) == 10:
            candidates = Partner.search([('phone', 'like', mobile[-6:])], limit=50).filtered(
                lambda p: _digits(p.phone)[-10:] == mobile)
            gender = (patient.get('gender') or '').upper()[:1]
            year = patient.get('yearOfBirth')
            first = (patient.get('name') or '').strip().split(' ')[0].lower()
            for cand in candidates:
                demo = cand._abdm_demographics()
                if (demo.get('gender') or 'O') != (gender or 'O'):
                    continue
                if year and demo.get('year_of_birth') and int(year) != int(demo['year_of_birth']):
                    continue
                if first and not (cand.name or '').lower().startswith(first):
                    continue
                return cand, ['MOBILE']
        return Partner.browse(), []
