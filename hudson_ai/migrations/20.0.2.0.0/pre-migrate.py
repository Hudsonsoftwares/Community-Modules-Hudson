# Part of Hudson Community. See LICENSE file for full copyright and licensing details.
"""2.0 moves the configuration from the hudson.ai.config model to Settings
(ir.config_parameter). Copy the old primary configuration before the model is removed."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("SELECT to_regclass('hudson_ai_config')")
    if not cr.fetchone()[0]:
        return
    cr.execute("""
        SELECT provider, base_url, api_key, model_name
          FROM hudson_ai_config
         WHERE active
      ORDER BY is_primary DESC, id DESC
         LIMIT 1
    """)
    row = cr.fetchone()
    if not row:
        return
    provider, base_url, api_key, model_name = row
    provider = {'lm_studio': 'custom'}.get(provider, provider or 'groq')
    # Keys pasted together with other text (e.g. "gsk_... copy") never worked:
    # keep only the first word.
    api_key = (api_key or '').split()[0] if (api_key or '').strip() else ''
    if api_key == 'lm-studio':
        api_key = ''
    if provider == 'groq' and model_name == 'llama-3.3-70b-versatile':
        model_name = ''  # enterprise-only on Groq now; use the provider default
    params = {
        'hudson_ai.provider': provider,
        'hudson_ai.api_key': api_key,
        'hudson_ai.model': model_name or '',
        'hudson_ai.base_url': base_url if provider == 'custom' else '',
    }
    for key, value in params.items():
        if not value:
            continue
        cr.execute("""
            INSERT INTO ir_config_parameter (key, value, create_uid, write_uid, create_date, write_date)
            VALUES (%s, %s, 1, 1, now() at time zone 'UTC', now() at time zone 'UTC')
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, (key, value))
    _logger.info('Hudson AI: moved configuration (provider %s) to Settings', provider)
