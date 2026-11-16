from odoo import api, fields, models


def _parse_dt(value):
    """ABDM ISO timestamps ('2026-11-12T10:00:00.000Z') -> naive UTC datetime."""
    if not value:
        return False
    text = str(value).replace('T', ' ').replace('Z', '')
    text = text.split('+')[0].split('.')[0]
    try:
        return fields.Datetime.to_datetime(text)
    except ValueError:
        return False


class AbdmConsent(models.Model):
    """Consent artefact ABDM sends the facility when a patient grants (or
    revokes) access to records held here."""
    _name = 'abdm.consent'
    _description = 'ABDM Consent (HIP)'
    _order = 'id desc'
    _rec_name = 'consent_id'

    consent_id = fields.Char(string='Consent ID', required=True, index=True, readonly=True)
    status = fields.Selection([
        ('GRANTED', 'Granted'),
        ('REVOKED', 'Revoked'),
        ('EXPIRED', 'Expired'),
        ('DENIED', 'Denied'),
    ], required=True, readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', string='Patient', readonly=True, index=True)
    patient_abha_address = fields.Char(readonly=True)
    hip_id = fields.Char(readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    purpose = fields.Char(readonly=True)
    hi_types = fields.Char(string='Record Types', readonly=True)
    care_context_ids = fields.Many2many('abdm.care.context', string='Care Contexts', readonly=True)
    date_from = fields.Datetime(string='Records From', readonly=True)
    date_to = fields.Datetime(string='Records To', readonly=True)
    erase_at = fields.Datetime(string='Data Erase At', readonly=True)
    access_mode = fields.Char(readonly=True)
    artefact = fields.Json(readonly=True, groups='abdm_base.group_abdm_manager')
    transfer_ids = fields.One2many('abdm.data.transfer', 'consent_ref_id', string='Transfers')

    _consent_uniq = models.Constraint('UNIQUE(consent_id)', 'Consent already recorded.')

    def _is_usable(self):
        self.ensure_one()
        now = fields.Datetime.now()
        return self.status == 'GRANTED' and (not self.erase_at or self.erase_at > now)

    @api.model
    def _from_notification(self, notification):
        """Create or update the consent from a hip/notify payload."""
        detail = notification.get('consentDetail') or {}
        consent_id = notification.get('consentId') or detail.get('consentId')
        status = (notification.get('status') or '').upper() or 'GRANTED'
        consent = self.sudo().search([('consent_id', '=', consent_id)], limit=1)
        if consent and not detail:
            consent.status = status if status in dict(self._fields['status'].selection) else consent.status
            return consent

        hip_id = (detail.get('hip') or {}).get('id')
        company = self.env['res.company'].sudo().search([('abdm_hip_id', '=', hip_id)], limit=1) if hip_id else False
        refs = [c.get('careContextReference') for c in detail.get('careContexts') or [] if c.get('careContextReference')]
        domain = [('reference', 'in', refs)]
        if company:
            domain.append(('company_id', '=', company.id))
        contexts = self.env['abdm.care.context'].sudo().search(domain) if refs else self.env['abdm.care.context']
        permission = detail.get('permission') or {}
        date_range = permission.get('dateRange') or {}
        vals = {
            'consent_id': consent_id,
            'status': status if status in dict(self._fields['status'].selection) else 'GRANTED',
            'partner_id': contexts[:1].partner_id.id,
            'patient_abha_address': (detail.get('patient') or {}).get('id'),
            'hip_id': hip_id,
            'company_id': company.id if company else False,
            'purpose': (detail.get('purpose') or {}).get('text') or (detail.get('purpose') or {}).get('code'),
            'hi_types': ','.join(detail.get('hiTypes') or []),
            'care_context_ids': [(6, 0, contexts.ids)],
            'date_from': _parse_dt(date_range.get('from')),
            'date_to': _parse_dt(date_range.get('to')),
            'erase_at': _parse_dt(permission.get('dataEraseAt')),
            'access_mode': permission.get('accessMode'),
            'artefact': notification,
        }
        if consent:
            consent.write(vals)
        else:
            consent = self.sudo().create(vals)
        return consent


class AbdmDataTransfer(models.Model):
    """One health-information request answered by this facility."""
    _name = 'abdm.data.transfer'
    _description = 'ABDM Data Transfer (HIP)'
    _order = 'id desc'
    _rec_name = 'transaction_id'

    transaction_id = fields.Char(required=True, index=True, readonly=True)
    consent_id = fields.Char(string='Consent ID', readonly=True, index=True)
    consent_ref_id = fields.Many2one('abdm.consent', string='Consent', readonly=True, ondelete='set null')
    partner_id = fields.Many2one(related='consent_ref_id.partner_id', string='Patient')
    state = fields.Selection([
        ('requested', 'Requested'),
        ('transferred', 'Transferred'),
        ('failed', 'Failed'),
    ], default='requested', readonly=True, index=True)
    data_push_url = fields.Char(readonly=True)
    date_from = fields.Datetime(readonly=True)
    date_to = fields.Datetime(readonly=True)
    record_count = fields.Integer(string='Records Sent', readonly=True)
    details = fields.Text(readonly=True)
    error_message = fields.Text(readonly=True)
