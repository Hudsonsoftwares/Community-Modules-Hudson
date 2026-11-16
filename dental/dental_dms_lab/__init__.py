# -*- coding: utf-8 -*-
from . import models


def post_init_hook(env):
    service = env['dental.dms.service'].sudo()
    for company in env['res.company'].sudo().search([]):
        service._sync_folder_permissions(service._get_category_folder(company, 'lab'))
    service._route_existing_attachments(['dental.lab.order', 'dental.lab.dispatch', 'dental.lab.receipt'])
