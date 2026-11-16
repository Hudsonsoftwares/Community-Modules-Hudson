from odoo import api, models


class AbdmTransaction(models.Model):
    _inherit = 'abdm.transaction'

    @api.model
    def _cron_expire(self):
        res = super()._cron_expire()
        minutes = self.env['ir.config_parameter'].sudo().get_int(
            'abdm_base.transaction_timeout_minutes', 30) or 30
        self.env['insurance.eligibility']._nhcx_expire(minutes)
        return res
