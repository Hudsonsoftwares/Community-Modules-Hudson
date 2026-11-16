# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Field service rights are now given by the Planning rights (the
    "Field Service" selector is gone from the user settings): users who were
    given Field Service rights get the matching Planning rights instead."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    mapping = [
        ('hudson_field_service.group_field_service_manager', 'hudson_planning.group_planning_manager'),
        ('hudson_field_service.group_field_service_user', 'hudson_planning.group_planning_user'),
    ]
    for fs_xmlid, planning_xmlid in mapping:
        fs_group = env.ref(fs_xmlid, raise_if_not_found=False)
        planning_group = env.ref(planning_xmlid, raise_if_not_found=False)
        if not fs_group or not planning_group:
            continue
        users = env['res.users'].with_context(active_test=False).search([('group_ids', 'in', fs_group.ids)])
        if users:
            users.write({'group_ids': [(4, planning_group.id), (3, fs_group.id)]})
