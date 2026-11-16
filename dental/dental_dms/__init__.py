# -*- coding: utf-8 -*-
from . import models
from . import wizard


def post_init_hook(env):
    """Create the dental folder tree for every company and file existing attachments."""
    service = env['dental.dms.service'].sudo()
    for company in env['res.company'].sudo().search([]):
        service._ensure_category_folders(company)
    service._route_existing_attachments()
