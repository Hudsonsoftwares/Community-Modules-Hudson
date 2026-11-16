# -*- coding: utf-8 -*-
from . import models


def post_init_hook(env):
    """Medicines must be sellable at the counter: existing medicines become available in POS."""
    templates = env['product.template'].with_context(active_test=False).search([
        ('is_medicine', '=', True), ('available_in_pos', '=', False), ('sale_ok', '=', True)])
    templates.write({'available_in_pos': True})
