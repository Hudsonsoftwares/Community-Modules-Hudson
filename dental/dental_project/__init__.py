from . import models


def post_init_hook(env):
    """Existing data on install: dental treatments invoice what was delivered, and every open
    treatment plan gets its project with one task per step."""
    env['product.template']._dental_set_delivery_invoicing()
    plans = env['dental.treatment.plan'].search([('state', 'not in', ('cancelled',))])
    plans._dental_ensure_project()
