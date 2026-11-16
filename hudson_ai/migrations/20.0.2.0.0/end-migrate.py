# Part of Hudson Community. See LICENSE file for full copyright and licensing details.
"""Drop the table of the removed hudson.ai.config model: it still holds the old API key."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    if 'hudson.ai.config' not in env:
        cr.execute("DROP TABLE IF EXISTS hudson_ai_config CASCADE")
