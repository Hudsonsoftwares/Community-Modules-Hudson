import json

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    abdm_environment = fields.Selection([
        ('sandbox', 'Sandbox (testing)'),
        ('production', 'Production (live)'),
    ], string='ABDM Environment', default='sandbox', config_parameter='abdm_base.environment')
    abdm_client_id = fields.Char(string='ABDM Client ID', config_parameter='abdm_base.client_id')
    abdm_client_secret = fields.Char(string='ABDM Client Secret', config_parameter='abdm_base.client_secret')
    abdm_callback_url = fields.Char(
        string='Public Callback URL', config_parameter='abdm_base.callback_url',
        help='Public HTTPS address of this Odoo (e.g. https://yourdomain.com). '
             'ABDM sends its answers to <this URL>/api/v3/...')
    abdm_verify_callbacks = fields.Boolean(
        string='Verify ABDM Signature', default=True, config_parameter='abdm_base.verify_callbacks',
        help='Reject callbacks that are not signed by the ABDM gateway. Keep it on.')
    abdm_gateway_url = fields.Char(
        string='Gateway URL Override', config_parameter='abdm_base.gateway_url',
        help='Leave empty to use the standard URL of the selected environment.')
    abdm_abha_url = fields.Char(
        string='ABHA URL Override', config_parameter='abdm_base.abha_url',
        help='Leave empty to use the standard URL of the selected environment.')
    abdm_cm_id = fields.Char(
        string='X-CM-ID Override', config_parameter='abdm_base.cm_id',
        help='Leave empty: sbx for sandbox, abdm for production.')
    abdm_log_retention_days = fields.Integer(
        string='Keep Logs (days)', default=90, config_parameter='abdm_base.log_retention_days')
    abdm_hip_id = fields.Char(related='company_id.abdm_hip_id', readonly=False)
    abdm_hip_name = fields.Char(related='company_id.abdm_hip_name', readonly=False)

    def _abdm_notify(self, title, message, kind='success', sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': title, 'message': message, 'type': kind, 'sticky': sticky},
        }

    def action_abdm_test_connection(self):
        self.execute()  # save what was typed before testing it
        info = self.env['abdm.gateway'].test_connection()
        return self._abdm_notify(
            self.env._("Connected to ABDM"),
            self.env._("Login successful (%(env)s, X-CM-ID %(cm)s).", env=info['environment'], cm=info['cm_id']),
        )

    def action_abdm_register_bridge_url(self):
        self.execute()
        url = self.env['abdm.gateway']._get_config()['callback_url']
        self.env['abdm.gateway'].register_bridge_url(url)
        return self._abdm_notify(
            self.env._("Bridge URL registered"),
            self.env._("ABDM will now send its answers to %s", url),
        )

    def action_abdm_bridge_services(self):
        self.execute()
        data = self.env['abdm.gateway'].get_bridge_services()
        text = json.dumps(data, indent=1, ensure_ascii=False) if data else self.env._(
            "No facility is linked to this client ID yet.")
        return self._abdm_notify(self.env._("Services linked to your client ID"), text[:1500],
                                 kind='info', sticky=True)
