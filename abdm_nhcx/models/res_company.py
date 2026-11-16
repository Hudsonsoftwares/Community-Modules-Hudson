from odoo import api, fields, models
from odoo.exceptions import UserError

from ..tools import jwe


class ResCompany(models.Model):
    _inherit = 'res.company'

    nhcx_participant_code = fields.Char(
        string='NHCX Participant Code', copy=False, index=True,
        help='Code of this facility in the NHCX participant registry (given at onboarding; '
             'providers are usually registered with their HFR ID).')
    nhcx_private_key = fields.Text(
        string='NHCX Private Key', copy=False, groups='base.group_system',
        help='Decrypts the answers payers send to this facility. Never share it.')
    nhcx_certificate = fields.Text(
        string='NHCX Encryption Certificate', copy=False,
        help='Public certificate to upload in the NHCX participant registry: payers use it '
             'to encrypt their answers to this facility.')
    nhcx_certificate_expiry = fields.Datetime(
        string='Certificate Valid Until', compute='_compute_nhcx_certificate_info')

    @api.depends('nhcx_certificate')
    def _compute_nhcx_certificate_info(self):
        for company in self:
            expiry = False
            if company.nhcx_certificate:
                try:
                    expiry = jwe.certificate_info(company.nhcx_certificate)['not_after'].replace(tzinfo=None)
                except ValueError:
                    expiry = False
            company.nhcx_certificate_expiry = expiry

    def _nhcx_generate_keys(self, overwrite=False):
        self.ensure_one()
        if not self.env.is_system():
            raise UserError(self.env._("Only administrators can generate NHCX keys."))
        company = self.sudo()
        if company.nhcx_private_key and not overwrite:
            raise UserError(self.env._(
                "%s already has NHCX keys. New keys make the certificate registered with NHCX "
                "useless until you upload the new one.", company.display_name))
        common_name = company.nhcx_participant_code or company.abdm_hip_id or company.name
        private_pem, cert_pem = jwe.generate_key_pair(common_name, organization=company.name)
        company.write({'nhcx_private_key': private_pem, 'nhcx_certificate': cert_pem})
        return cert_pem
