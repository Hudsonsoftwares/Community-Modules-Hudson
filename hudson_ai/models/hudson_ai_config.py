# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import urllib.request
import urllib.error
import json
import logging

_logger = logging.getLogger(__name__)


class HudsonAIConfig(models.Model):
    """
    Stores LM Studio connection settings for the Hudson AI assistant.
    There is always exactly one active configuration record (singleton pattern).
    """
    _name = 'hudson.ai.config'
    _description = 'Hudson AI Configuration'

    name = fields.Char(
        string='Configuration Name',
        required=True,
        default='Default',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    is_primary = fields.Boolean(
        string='Primary Configuration',
        default=False,
        help='Check this to make this the active configuration used by the AI assistant.'
    )
    enabled = fields.Boolean(
        string='Enable AI Assistant',
        default=True,
        help='When disabled the AI systray icon is hidden from all users.',
    )

    # ── AI Provider & Connection ───────────────────────────────────────────────
    provider = fields.Selection([
        ('lm_studio', 'LM Studio (Local)'),
        ('groq', 'Groq (Cloud)'),
        ('gemini', 'Google Gemini (Free Cloud)'),
    ], string='AI Provider', default='lm_studio', required=True)

    base_url = fields.Char(
        string='API Base URL',
        required=True,
        default='http://localhost:1234/v1',
        help='The base URL of the OpenAI-compatible API (e.g. http://localhost:1234/v1 or https://api.groq.com/openai/v1)',
    )
    api_key = fields.Char(
        string='API Key',
        default='lm-studio',
        help='API key for the provider. LM Studio accepts any non-empty string. Groq requires a valid API key.',
    )
    model_name = fields.Char(
        string='Model Name',
        required=True,
        default='gemma-3-12b-it',
        help='The model identifier, e.g. gemma-3-12b-it (LM Studio) or llama-3.3-70b-versatile (Groq)',
    )

    @api.onchange('provider')
    def _onchange_provider(self):
        if self.provider == 'groq':
            self.base_url = 'https://api.groq.com/openai/v1'
            self.model_name = 'llama-3.3-70b-versatile'
            self.api_key = ''
        elif self.provider == 'gemini':
            self.base_url = 'https://generativelanguage.googleapis.com/v1beta/openai/'
            self.model_name = 'gemini-3.6-flash'
            self.api_key = ''
        elif self.provider == 'lm_studio':
            self.base_url = 'http://localhost:1234/v1'
            self.model_name = 'gemma-3-12b-it'
            self.api_key = 'lm-studio'

    # ── Generation Parameters ─────────────────────────────────────────────────
    temperature = fields.Float(
        string='Temperature',
        default=0.3,
        help='Controls randomness. 0.0 = deterministic, 1.0 = very creative. '
             'Keep low (0.1-0.4) for database operations.',
    )
    max_tokens = fields.Integer(
        string='Max Response Tokens',
        default=2048,
        help='Maximum number of tokens the model can generate per response.',
    )
    system_prompt = fields.Text(
        string='System Prompt',
        help='Leave blank to use the default system prompt. '
             'You can customise the AI personality here.',
    )
    connection_status = fields.Char(
        string='Connection Status',
        readonly=True,
        default='Not tested',
    )

    # ── Singleton helpers ─────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('is_primary'):
                self.search([('is_primary', '=', True)]).write({'is_primary': False})
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('is_primary'):
            self.search([('id', '!=', self.id), ('is_primary', '=', True)]).write({'is_primary': False})
        return super().write(vals)

    @api.model
    def get_config(self):
        """Return the primary config record. Fallback to the newest if none is primary."""
        config = self.search([('is_primary', '=', True), ('active', '=', True)], limit=1)
        if not config:
            config = self.search([('active', '=', True)], order='id desc', limit=1)
        if not config:
            config = self.create({'name': 'Default', 'is_primary': True})
        return config

    @api.model
    def get_config_dict(self):
        """Return a plain dict of the active config (used by the controller)."""
        cfg = self.get_config()
        return {
            'enabled': cfg.enabled,
            'base_url': cfg.base_url or 'http://localhost:1234/v1',
            'api_key': cfg.api_key or 'lm-studio',
            'model_name': cfg.model_name or 'gemma-3-12b-it',
            'temperature': cfg.temperature,
            'max_tokens': cfg.max_tokens,
            'system_prompt': cfg.system_prompt or '',
        }

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_test_connection(self):
        """Ping the LM Studio server to verify connectivity."""
        self.ensure_one()
        api_key = (self.api_key or 'lm-studio').strip()
        url = (self.base_url or '').strip().rstrip('/') + '/models'
        try:
            if self.provider == 'gemini' or 'generativelanguage.googleapis.com' in (self.base_url or ''):
                # Hardcode Gemini's correct OpenAI proxy URL to prevent 404s from user typos
                test_url = 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'
                payload = json.dumps({'model': self.model_name, 'messages': [{'role': 'user', 'content': 'hi'}], 'max_tokens': 1}).encode('utf-8')
                req = urllib.request.Request(
                    test_url,
                    data=payload,
                    headers={
                        'Authorization': f'Bearer {api_key}',
                        'Content-Type': 'application/json',
                    },
                    method='POST',
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    status = f'✓ Connected to Google Gemini successfully!'
                    self.write({'connection_status': status})
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Connection Successful'),
                            'message': status,
                            'type': 'success',
                            'sticky': False,
                        },
                    }
            else:
                req = urllib.request.Request(
                    url,
                    headers={
                        'Authorization': f'Bearer {api_key}',
                        'Content-Type': 'application/json',
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'application/json',
                    },
                    method='GET',
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode())
                    models_list = [m.get('id', '') for m in data.get('data', [])]
                    status = f'✓ Connected — {len(models_list)} model(s) available: {", ".join(models_list[:3])}'
                    self.write({'connection_status': status})
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Connection Successful'),
                            'message': status,
                            'type': 'success',
                            'sticky': False,
                        },
                    }
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode())
                err_msg = err_body.get('error', {}).get('message', str(e))
            except Exception:
                err_msg = str(e)
                
            status = f'✗ Failed: HTTP {e.code} - {err_msg}'
            self.write({'connection_status': status})
            if e.code in (401, 403):
                raise UserError(_('Authentication Failed (HTTP %s): %s\n\nPlease check that your API Key is correct and has the necessary permissions.') % (e.code, err_msg))
            raise UserError(_('API Error (HTTP %s):\n\n%s') % (e.code, err_msg))
            
        except urllib.error.URLError as e:
            status = f'✗ Failed: {e.reason}'
            self.write({'connection_status': status})
            
            # Custom help based on provider
            if self.provider == 'lm_studio':
                help_text = 'Make sure LM Studio is running and the Local Server is started.'
            else:
                help_text = 'Check your internet connection and verify that the Base URL is correct.'
                
            raise UserError(
                _('Cannot reach the AI Provider at %s.\n\nError: %s\n\n%s') % (url, e.reason, help_text)
            )
        except Exception as e:
            status = f'✗ Error: {e}'
            self.write({'connection_status': status})
            raise UserError(_('Unexpected error: %s') % str(e))

    def action_open_config(self):
        """Client action to open the configuration form (used from systray)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Hudson AI Configuration'),
            'res_model': 'hudson.ai.config',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }
