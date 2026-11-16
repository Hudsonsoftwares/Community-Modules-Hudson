from odoo import api, fields, models

from .. import const


class ResPartner(models.Model):
    _inherit = 'res.partner'

    insurance_connector = fields.Selection(
        selection_add=[('nhcx', 'NHCX (India)')], ondelete={'nhcx': 'set default'})
    nhcx_participant_code = fields.Char(
        string='NHCX Participant Code', copy=False, index=True,
        help='Code of this insurer / TPA in the NHCX participant registry.')
    nhcx_encryption_cert = fields.Text(
        string='NHCX Encryption Certificate', copy=False,
        help='Public certificate of the payer: requests to it are encrypted with it.')
    nhcx_participant_status = fields.Char(string='NHCX Status', copy=False, readonly=True)

    _nhcx_participant_code_uniq = models.Constraint(
        'UNIQUE(nhcx_participant_code)', 'This NHCX participant code is already used by another contact.')

    @api.model
    def _nhcx_upsert_participant(self, participant, partner_type):
        """Create or update the payer for one registry entry."""
        client = self.env['nhcx.client']
        code = participant['participant_code']
        partner = self.with_context(active_test=False).search(
            [('nhcx_participant_code', '=', code)], limit=1)
        vals = {
            'nhcx_participant_status': participant.get('status') or False,
            'insurance_connector': 'nhcx',
        }
        cert = participant.get('encryption_cert')
        if cert:
            vals['nhcx_encryption_cert'] = client.fetch_certificate(cert)
        if not partner:
            vals.update({
                'name': participant.get('participant_name') or code,
                'is_company': True,
                'insurance_partner_type': partner_type,
                'nhcx_participant_code': code,
                'email': participant.get('primary_email') or False,
                'phone': participant.get('primary_mobile') or False,
            })
            return self.create(vals)
        if not partner.insurance_partner_type:
            vals['insurance_partner_type'] = partner_type
        partner.write(vals)
        return partner

    def action_nhcx_refresh(self):
        """Reload status and encryption certificate from the NHCX registry."""
        client = self.env['nhcx.client']
        for partner in self.filtered('nhcx_participant_code'):
            found = client.participant_search({'participant_code': {'eq': partner.nhcx_participant_code}})
            if not found:
                partner.nhcx_participant_status = self.env._('Not found in the NHCX registry')
                continue
            participant = found[0]
            roles = participant.get('roles') or []
            partner_type = 'tpa' if const.ROLE_TPA in roles else 'insurer'
            self._nhcx_upsert_participant(participant, partner_type)
        return True
