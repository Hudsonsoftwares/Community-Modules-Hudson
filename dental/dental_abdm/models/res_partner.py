from odoo import api, models

ABHA_GENDER_TO_DENTAL = {'M': 'male', 'F': 'female', 'O': 'other', 'T': 'other'}
DENTAL_GENDER_TO_ABHA = {'male': 'M', 'female': 'F', 'other': 'O'}


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _abdm_partner_vals_from_profile(self, profile, for_create=False):
        vals = super()._abdm_partner_vals_from_profile(profile, for_create=for_create)
        if profile.get('dob'):
            vals['date_of_birth'] = profile['dob']
        gender = ABHA_GENDER_TO_DENTAL.get(profile.get('gender') or '')
        if gender:
            vals['gender'] = gender
        if for_create:
            # Everyone registered through ABHA at the clinic is a patient
            # (dental_patient then assigns the Patient ID).
            vals['is_dental_patient'] = True
        return vals

    # --- abdm_hip hooks ------------------------------------------------
    def _abdm_patient_reference(self):
        self.ensure_one()
        if self.dental_patient_id and self.dental_patient_id != 'New':
            return self.dental_patient_id
        return super()._abdm_patient_reference()

    def _abdm_demographics(self):
        self.ensure_one()
        result = super()._abdm_demographics()
        result['gender'] = DENTAL_GENDER_TO_ABHA.get(self.gender, 'O')
        if self.date_of_birth:
            result['year_of_birth'] = self.date_of_birth.year
        return result

    def _abdm_care_context_sources(self, company=None):
        self.ensure_one()
        domain = [('patient_id', '=', self.id), ('state', '!=', 'cancelled')]
        if company:
            domain += ['|', ('branch_id', '=', company.id), ('branch_id', '=', False)]
        return self.env['dental.case'].sudo().search(domain)
