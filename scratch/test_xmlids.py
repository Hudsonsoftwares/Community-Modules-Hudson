import sys
sys.path.insert(0, r"C:\Program Files\Odoo 20.0.20260927\server")
import odoo
from odoo import tools

tools.config.parse_config(['-c', r'C:\Program Files\Odoo 20.0.20260927\server\odoo.conf'])
registry = odoo.modules.registry.Registry('HudsonTest')
with registry.cursor() as cr:
    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
    test_ids = [
        'account.action_account_invoice_report_all',
        'account.action_account_audit_trail_report',
        'account.action_move_line_select',
    ]
    for xmlid in test_ids:
        try:
            res = env.ref(xmlid, raise_if_not_found=False)
            print(f'{xmlid}: {"FOUND" if res else "NOT FOUND"}')
        except Exception as e:
            print(f'{xmlid}: ERROR -> {e}')
