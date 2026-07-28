# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from . import models
from . import wizard
from . import controllers


def post_init_hook(env):
    """
    Assign the OdooBot / Administrator user to Social Marketing groups after install.
    Needed because Odoo 19 removed the 'users' field from res.groups XML records.
    """
    import logging
    _logger = logging.getLogger(__name__)

    try:
        manager_group = env.ref('hudson_social_marketing.group_social_manager', raise_if_not_found=False)
        if not manager_group:
            return

        # Add all current admin-level users to the manager group
        admin_group = env.ref('base.group_erp_manager', raise_if_not_found=False)
        if admin_group:
            admin_users = admin_group.with_context(active_test=False).mapped('users')
            if admin_users:
                manager_group.write({'users': [(4, u.id) for u in admin_users]})
                _logger.info(
                    "Hudson Social Marketing: Added %d admin user(s) to Social Marketing / Administrator group.",
                    len(admin_users),
                )

        # Always make sure the install user (uid=1 or current) is in the group
        current_user = env.user
        if current_user and current_user not in manager_group.users:
            manager_group.write({'users': [(4, current_user.id)]})
            _logger.info("Hudson Social Marketing: Added current user (%s) to manager group.", current_user.login)

    except Exception as e:
        _logger.warning("Hudson Social Marketing post_init_hook failed (non-fatal): %s", e)

