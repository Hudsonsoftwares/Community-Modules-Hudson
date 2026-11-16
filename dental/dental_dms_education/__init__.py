# -*- coding: utf-8 -*-
from . import controllers
from . import models
from . import wizard


def post_init_hook(env):
    """Create the education category folder (with its permission lines) in every branch."""
    service = env['dental.dms.service'].sudo()
    for company in env['res.company'].sudo().search([]):
        service._get_category_folder(company, 'education')
