import sys
sys.path.append(r'C:\Program Files\Odoo 19.0.20260518\server')
import odoo
from odoo import api, SUPERUSER_ID

if __name__ == "__main__":
    odoo.tools.config.parse_config(['-c', r'C:\Program Files\Odoo 19.0.20260518\server\odoo.conf'])
    registry = odoo.registry('hudson-community')
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        env['hudson.social.account'].sync_from_remote()
        
        accounts = env['hudson.social.account'].search([])
        print("Total local accounts:", len(accounts))
        for a in accounts:
            print(f"ID: {a.id}, Name: {a.name}, Media Type: {a.media_type}, Remote ID: {a.remote_id}")
