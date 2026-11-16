import hashlib
import secrets
from datetime import timedelta

from odoo import api, fields, models

from ..const import LINK_TOKEN_VALIDITY_DAYS, OTP_VALIDITY_MINUTES


class AbdmLinkToken(models.Model):
    """Link token ABDM gives a facility for one patient (valid about 6 months).

    Needed for every clinic-initiated link of a care context.
    """
    _name = 'abdm.link.token'
    _description = 'ABDM Link Token'
    _order = 'id desc'

    partner_id = fields.Many2one('res.partner', required=True, index=True, ondelete='cascade')
    hip_id = fields.Char(required=True, index=True)
    token = fields.Char(required=True, groups='abdm_base.group_abdm_manager')
    expiry = fields.Datetime(required=True)
    abha_address = fields.Char()

    @api.model
    def _get_valid(self, partner, hip_id):
        rec = self.sudo().search([
            ('partner_id', '=', partner.id), ('hip_id', '=', hip_id),
            ('expiry', '>', fields.Datetime.now() + timedelta(minutes=5)),
        ], limit=1)
        return rec.token if rec else False

    @api.model
    def _store(self, partner, hip_id, token, abha_address=None):
        self.sudo().search([('partner_id', '=', partner.id), ('hip_id', '=', hip_id)]).unlink()
        return self.sudo().create({
            'partner_id': partner.id, 'hip_id': hip_id, 'token': token, 'abha_address': abha_address,
            'expiry': fields.Datetime.now() + timedelta(days=LINK_TOKEN_VALIDITY_DAYS),
        })


class AbdmLinkRequest(models.Model):
    """Patient-initiated linking: the patient picked care contexts in the ABHA
    app; we sent an OTP to their mobile and wait for confirmation."""
    _name = 'abdm.link.request'
    _description = 'ABDM Patient Link Request'
    _order = 'id desc'
    _rec_name = 'link_reference'

    transaction_id = fields.Char(required=True, index=True, readonly=True)
    link_reference = fields.Char(required=True, index=True, readonly=True,
                                 default=lambda self: secrets.token_hex(12))
    partner_id = fields.Many2one('res.partner', string='Patient', readonly=True, ondelete='cascade')
    abha_address = fields.Char(readonly=True)
    care_context_ids = fields.Many2many('abdm.care.context', string='Care Contexts', readonly=True)
    otp_hash = fields.Char(readonly=True, groups='base.group_system')
    otp_expiry = fields.Datetime(readonly=True)
    attempts = fields.Integer(readonly=True)
    state = fields.Selection([
        ('otp_sent', 'Waiting for OTP'),
        ('linked', 'Linked'),
        ('failed', 'Failed'),
    ], default='otp_sent', readonly=True)
    sandbox_otp = fields.Char(string='OTP (sandbox only)', readonly=True,
                              help='Shown only in the sandbox, so testers without SMS credits can finish the flow.')

    @staticmethod
    def _hash(otp, salt):
        return hashlib.sha256(('%s:%s' % (salt, otp)).encode()).hexdigest()

    def _issue_otp(self):
        self.ensure_one()
        otp = '%06d' % secrets.randbelow(1000000)
        sandbox = self.env['abdm.gateway']._get_config()['environment'] == 'sandbox'
        self.sudo().write({
            'otp_hash': self._hash(otp, self.link_reference),
            'otp_expiry': fields.Datetime.now() + timedelta(minutes=OTP_VALIDITY_MINUTES),
            'sandbox_otp': otp if sandbox else False,
        })
        return otp

    def _check_otp(self, otp):
        """True when ``otp`` is right and still valid (max 3 attempts)."""
        self.ensure_one()
        me = self.sudo()
        if me.state != 'otp_sent' or not me.otp_expiry or me.otp_expiry < fields.Datetime.now():
            return False
        me.attempts += 1
        if me.attempts > 3:
            me.state = 'failed'
            return False
        return secrets.compare_digest(me.otp_hash or '', self._hash(str(otp or '').strip(), me.link_reference))
