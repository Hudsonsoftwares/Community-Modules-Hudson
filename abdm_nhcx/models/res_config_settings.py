from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nhcx_api_url = fields.Char(
        string='NHCX API URL', config_parameter='abdm_nhcx.api_url',
        help='Base URL of the NHCX APIs for the selected environment (from the NHCX onboarding kit).')
    nhcx_auth_mode = fields.Selection([
        ('abdm', 'ABDM client (same Client ID / Secret)'),
        ('token', 'Separate NHCX login'),
    ], string='NHCX Login', default='abdm', config_parameter='abdm_nhcx.auth_mode',
        help='NHCX roles are normally attached to your ABDM client: keep "ABDM client" unless '
             'NHA gave you separate NHCX credentials.')
    nhcx_token_url = fields.Char(string='NHCX Token URL', config_parameter='abdm_nhcx.token_url')
    nhcx_username = fields.Char(string='NHCX Username', config_parameter='abdm_nhcx.username')
    nhcx_secret = fields.Char(string='NHCX Secret', config_parameter='abdm_nhcx.secret')
    nhcx_participant_code = fields.Char(related='company_id.nhcx_participant_code', readonly=False)
    nhcx_certificate = fields.Text(related='company_id.nhcx_certificate')
    nhcx_certificate_expiry = fields.Datetime(related='company_id.nhcx_certificate_expiry')
    nhcx_has_keys = fields.Boolean(compute='_compute_nhcx_endpoint')
    nhcx_endpoint_url = fields.Char(
        string='Your NHCX Endpoint', compute='_compute_nhcx_endpoint',
        help='Give this address during NHCX onboarding: payers answer on <endpoint>/<action>.')

    @api.depends('company_id')
    def _compute_nhcx_endpoint(self):
        callback = self.env['abdm.gateway']._get_config()['callback_url']
        for settings in self:
            settings.nhcx_endpoint_url = (callback + '/nhcx') if callback else False
            settings.nhcx_has_keys = bool(settings.company_id.sudo().nhcx_private_key)

    def action_nhcx_generate_keys(self):
        self.execute()
        self.company_id._nhcx_generate_keys(overwrite=self.env.context.get('nhcx_overwrite'))
        return self._abdm_notify(
            self.env._("NHCX keys generated"),
            self.env._("Upload the certificate shown under NHCX in the participant registry."))

    def action_nhcx_test_connection(self):
        self.execute()
        config = self.env['nhcx.client'].test_connection()
        return self._abdm_notify(self.env._("Connected to NHCX"),
                                 self.env._("Login successful (%s).", config['api_url']))

    def action_nhcx_sync_payers(self):
        self.execute()
        count = self.env['nhcx.client'].sync_payers()
        return self._abdm_notify(self.env._("NHCX payers synchronised"),
                                 self.env._("%s insurers / TPAs created or updated.", count))
