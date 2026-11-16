# Part of Hudson Community. See LICENSE file for full copyright and licensing details.
"""Minimal client for OpenAI-compatible chat completion APIs (Groq, Gemini, LM Studio,
or another Odoo running the Hudson AI gateway)."""

import logging
import time

import requests

from odoo import _

_logger = logging.getLogger(__name__)

PROVIDERS = {
    'groq': {
        'label': 'Groq',
        'url': 'https://api.groq.com/openai/v1',
        'model': 'openai/gpt-oss-120b',
    },
    'gemini': {
        'label': 'Google Gemini',
        'url': 'https://generativelanguage.googleapis.com/v1beta/openai',
        'model': 'gemini-3.6-flash',
        # Gemini 3.6+ rejects a custom temperature.
        'no_temperature': True,
    },
    'hudson': {
        'label': 'Hudson AI Gateway',
        'url': '',
        # The gateway decides the model.
        'model': 'gateway',
    },
    'custom': {
        'label': 'Other (OpenAI-compatible, e.g. LM Studio)',
        'url': 'http://localhost:1234/v1',
        'model': '',
    },
}
# Providers for which the user enters the URL.
URL_PROVIDERS = ('hudson', 'custom')

TEMPERATURE = 0.2
MAX_TOKENS = 1500
TIMEOUT = 90
# Cloudflare in front of Groq rejects urllib's default user agent.
USER_AGENT = 'HudsonAI/2.0 (Odoo)'
QUOTA_STATUS = 402


class AIProviderError(Exception):
    """Error with a message that can be shown to the user as is."""


def get_ai_settings(env):
    """Return the AI settings stored in ir.config_parameter (set from Settings)."""
    icp = env['ir.config_parameter'].sudo()
    provider = icp.get_str('hudson_ai.provider') or 'groq'
    if provider not in PROVIDERS:
        provider = 'groq'
    defaults = PROVIDERS[provider]
    base_url = defaults['url']
    if provider in URL_PROVIDERS:
        base_url = icp.get_str('hudson_ai.base_url') or base_url
    model = defaults['model'] if provider == 'hudson' else (icp.get_str('hudson_ai.model') or defaults['model'])
    return {
        'provider': provider,
        'base_url': base_url.strip().rstrip('/'),
        'api_key': (icp.get_str('hudson_ai.api_key') or '').strip(),
        'model': model.strip(),
        'database': (icp.get_str('hudson_ai.gateway_database') or '').strip() if provider == 'hudson' else '',
    }


def is_configured(cfg):
    if cfg['provider'] == 'custom':
        return bool(cfg['base_url'] and cfg['model'])
    if cfg['provider'] == 'hudson':
        return bool(cfg['base_url'] and cfg['api_key'])
    return bool(cfg['api_key'])


def _headers(cfg):
    headers = {
        'Authorization': f"Bearer {cfg['api_key'] or 'none'}",
        'Content-Type': 'application/json',
        'User-Agent': USER_AGENT,
    }
    if cfg.get('database'):
        # Selects the gateway database on a multi-database Odoo server.
        headers['X-Odoo-Database'] = cfg['database']
    return headers


def _error_message(cfg, response):
    try:
        body = response.json()
        error = body[0] if isinstance(body, list) else body
        detail = (error.get('error') or {}).get('message') or response.text
    except ValueError:
        detail = response.text[:300]
    label = PROVIDERS[cfg['provider']]['label']
    if response.status_code == QUOTA_STATUS:
        return detail
    if response.status_code in (401, 403):
        return _('%(provider)s rejected the API key (HTTP %(code)s). Check the key in '
                 'Settings > Hudson AI.\n\n%(detail)s',
                 provider=label, code=response.status_code, detail=detail)
    if response.status_code == 404:
        if cfg['provider'] == 'hudson':
            return _('No Hudson AI gateway at %(url)s. Check the gateway URL and database in '
                     'Settings > Hudson AI.', url=cfg['base_url'])
        return _('%(provider)s does not know the model "%(model)s". Choose another model in '
                 'Settings > Hudson AI.\n\n%(detail)s',
                 provider=label, model=cfg['model'], detail=detail)
    if response.status_code == 413:
        return _('The request was too large for the model. Ask a narrower question.')
    if response.status_code == 429:
        return _('%(provider)s rate limit reached. Wait a minute and try again.\n\n%(detail)s',
                 provider=label, detail=detail)
    return _('%(provider)s error (HTTP %(code)s): %(detail)s',
             provider=label, code=response.status_code, detail=detail)


def _send(cfg, method, path, payload=None):
    try:
        return requests.request(method, cfg['base_url'] + path, json=payload,
                                headers=_headers(cfg), timeout=TIMEOUT)
    except requests.RequestException as e:
        raise AIProviderError(_('Cannot reach the AI provider at %(url)s: %(error)s',
                                url=cfg['base_url'], error=e)) from None


def _request(cfg, method, path, payload=None):
    if not is_configured(cfg):
        raise AIProviderError(_(
            'Hudson AI is not configured yet. An administrator must set it up in '
            'Settings > Hudson AI.'))
    for attempt in range(3):
        response = _send(cfg, method, path, payload)
        if response.ok:
            try:
                return response.json()
            except ValueError:
                raise AIProviderError(_('The AI provider returned an invalid response.')) from None
        if attempt < 2 and response.status_code == 429:
            try:
                wait = float(response.headers.get('retry-after') or 2)
            except ValueError:
                wait = 2
            if wait <= 15:
                _logger.info('Hudson AI: rate limited, retrying in %ss', wait)
                time.sleep(wait)
                continue
        if attempt < 2 and response.status_code == 400 and 'tool_use_failed' in response.text:
            # Groq: the model produced a malformed tool call. A retry usually works.
            _logger.info('Hudson AI: invalid tool call from the model, retrying')
            continue
        raise AIProviderError(_error_message(cfg, response))


def build_payload(cfg, messages, tools=None, max_tokens=MAX_TOKENS, temperature=TEMPERATURE):
    payload = {
        'model': cfg['model'],
        'messages': messages,
        'max_tokens': min(int(max_tokens or MAX_TOKENS), MAX_TOKENS),
    }
    if not PROVIDERS[cfg['provider']].get('no_temperature'):
        payload['temperature'] = temperature
    if tools:
        payload['tools'] = tools
        payload['tool_choice'] = 'auto'
    return payload


def chat_completion(cfg, messages, tools=None):
    """Call /chat/completions. Returns (assistant message dict, usage dict)."""
    data = _request(cfg, 'POST', '/chat/completions', build_payload(cfg, messages, tools))
    choices = data.get('choices') or [{}]
    return choices[0].get('message') or {}, data.get('usage') or {}


def forward(cfg, payload):
    """Gateway: send a client's request upstream once. Returns (status, body bytes, headers)."""
    response = _send(cfg, 'POST', '/chat/completions', payload)
    headers = {'Content-Type': response.headers.get('Content-Type', 'application/json')}
    if response.headers.get('retry-after'):
        headers['Retry-After'] = response.headers['retry-after']
    return response.status_code, response.content, headers


def list_models(cfg):
    """Return the model ids available for the configured key."""
    data = _request(cfg, 'GET', '/models')
    return [m['id'].removeprefix('models/') for m in data.get('data', []) if m.get('id')]


def gateway_usage(cfg):
    """Return the credits status of this database at its Hudson AI gateway."""
    return _request(cfg, 'GET', '/usage')
