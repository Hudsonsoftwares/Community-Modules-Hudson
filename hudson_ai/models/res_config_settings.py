# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .ai_provider import PROVIDERS, AIProviderError, gateway_usage, get_ai_settings, list_models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    hudson_ai_provider = fields.Selection(
        [(key, vals['label']) for key, vals in PROVIDERS.items()],
        string='AI Provider',
        default='groq',
        config_parameter='hudson_ai.provider',
    )
    hudson_ai_api_key = fields.Char(
        string='API Key',
        config_parameter='hudson_ai.api_key',
    )
    hudson_ai_model = fields.Char(
        string='Model',
        config_parameter='hudson_ai.model',
        help='Leave empty to use the recommended model of the provider.',
    )
    hudson_ai_base_url = fields.Char(
        string='Server URL',
        config_parameter='hudson_ai.base_url',
        help='OpenAI-compatible endpoint, e.g. http://localhost:1234/v1 for LM Studio, or '
             'https://your-hudson-server/hudson_ai/v1 for a Hudson AI gateway.',
    )
    hudson_ai_gateway_database = fields.Char(
        string='Gateway Database',
        config_parameter='hudson_ai.gateway_database',
        help='Database of the gateway server, needed when that server hosts several databases.',
    )
    hudson_ai_default_model = fields.Char(compute='_compute_hudson_ai_default_model')
    hudson_ai_gateway_enabled = fields.Boolean(
        string='Share with other databases',
        config_parameter='hudson_ai.gateway_enabled',
        help='Act as a Hudson AI gateway: other Odoo databases use this AI provider with their '
             'own key and credit limits.',
    )
    hudson_ai_client_count = fields.Integer(compute='_compute_hudson_ai_client_count')

    @api.depends('hudson_ai_provider')
    def _compute_hudson_ai_default_model(self):
        for settings in self:
            provider = settings.hudson_ai_provider or 'groq'
            settings.hudson_ai_default_model = '' if provider == 'hudson' else PROVIDERS[provider]['model']

    def _compute_hudson_ai_client_count(self):
        count = self.env['hudson.ai.client'].search_count([])
        for settings in self:
            settings.hudson_ai_client_count = count

    @api.onchange('hudson_ai_provider')
    def _onchange_hudson_ai_provider(self):
        # The model / URL of one provider is meaningless for another one.
        self.hudson_ai_model = False
        self.hudson_ai_base_url = False

    @api.constrains('hudson_ai_api_key')
    def _check_hudson_ai_api_key(self):
        for settings in self:
            key = (settings.hudson_ai_api_key or '').strip()
            if key and any(char.isspace() for char in key):
                raise ValidationError(_(
                    'The API key contains spaces. Paste only the key itself '
                    '(a Groq key looks like "gsk_..." and has no spaces).'
                ))

    @api.constrains('hudson_ai_provider', 'hudson_ai_gateway_enabled')
    def _check_hudson_ai_gateway(self):
        for settings in self:
            if settings.hudson_ai_gateway_enabled and settings.hudson_ai_provider == 'hudson':
                raise ValidationError(_('A database that uses a Hudson AI gateway cannot itself be a gateway.'))

    def action_hudson_ai_test(self):
        """Save the settings, then check the key and that the model is usable."""
        self.ensure_one()
        self.execute()
        cfg = get_ai_settings(self.env)
        try:
            if cfg['provider'] == 'hudson':
                usage = gateway_usage(cfg)
                message = self._hudson_ai_usage_message(usage)
            else:
                available = list_models(cfg)
                if available and cfg['model'] not in available:
                    raise UserError(_(
                        'The connection works, but the model "%(model)s" is not available for this key.\n\n'
                        'Available models: %(models)s',
                        model=cfg['model'], models=', '.join(sorted(available)),
                    ))
                message = _('Connected to %(provider)s with model %(model)s.',
                            provider=PROVIDERS[cfg['provider']]['label'], model=cfg['model'])
        except AIProviderError as e:
            raise UserError(str(e)) from None
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Hudson AI is ready'),
                'message': message,
                'type': 'success',
                'sticky': True,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def _hudson_ai_usage_message(self, usage):
        def limit(value):
            return f'{value:,}' if value else _('unlimited')
        return _(
            'Connected to the gateway as "%(client)s". This month: %(tokens)s of %(token_limit)s '
            'tokens. Today: %(calls)s of %(call_limit)s calls.',
            client=usage.get('client', ''),
            tokens=f"{usage.get('tokens_this_month', 0):,}",
            token_limit=limit(usage.get('monthly_token_limit')),
            calls=usage.get('requests_today', 0),
            call_limit=limit(usage.get('daily_request_limit')),
        )

    def action_hudson_ai_clients(self):
        return self.env['ir.actions.act_window']._for_xml_id('hudson_ai.action_hudson_ai_client')

    def action_hudson_ai_access_rules(self):
        return self.env['ir.actions.act_window']._for_xml_id('hudson_ai.action_hudson_ai_access_rule')
