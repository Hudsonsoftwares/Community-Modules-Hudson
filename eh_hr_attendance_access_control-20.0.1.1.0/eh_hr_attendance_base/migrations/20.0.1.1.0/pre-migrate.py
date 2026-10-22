# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""EH Attendance User and EH Attendance Auditor stop implying HR Officer.

Up to 20.0.1.0.0 both roles implied hr.group_hr_user, which is create, write
and delete on every employee and their private data. From 20.0.1.1.0 neither
does. Taking the implication away on upgrade would silently remove HR Officer
from every user who holds it only through one of the two roles, so before it
goes, each of those users is given HR Officer explicitly and their logins are
logged at INFO for an administrator to review and revoke. A user who holds HR
Officer any other way (assigned directly, through HR Administrator, through
EH Attendance Manager) is left alone, and nobody else gains anything.

"Only through the two roles" is decided on the implication graph itself: a
user is affected when HR Officer is in the closure of their groups, and is no
longer there once the two edges (role, HR Officer) are left out. A group of
another module that implies one of the roles is therefore covered too.
Archived users are included, so reactivating one later restores what they had.

This runs before the module data is loaded. The security file no longer
declares the implication, and records it no longer names are not cleared by
an update, so the two edges are removed here, after the grant. The translated
descriptions of the two roles, which state the implication, are dropped for
the same reason: an update only rewrites the English one.
"""
import logging
from collections import defaultdict

from odoo import SUPERUSER_ID, api
from odoo.fields import Command

_logger = logging.getLogger(__name__)

HR_OFFICER = 'hr.group_hr_user'
ROLES = (
    'eh_hr_attendance_base.group_eh_hr_user',
    'eh_hr_attendance_base.group_eh_hr_auditor',
)


def _closure(group_ids, implied, skipped=frozenset()):
    """Every group reached from ``group_ids`` through ``implied``, the
    (group, implied group) edges in ``skipped`` excepted."""
    reached = set(group_ids)
    stack = list(group_ids)
    while stack:
        group_id = stack.pop()
        for implied_id in implied.get(group_id, ()):
            if implied_id in reached or (group_id, implied_id) in skipped:
                continue
            reached.add(implied_id)
            stack.append(implied_id)
    return reached


def users_holding_officer_only_through_roles(env):
    """The users, archived ones included, who hold HR Officer today and would
    not hold it once the roles stop implying it."""
    officer = env.ref(HR_OFFICER, raise_if_not_found=False)
    roles = [env.ref(xmlid, raise_if_not_found=False) for xmlid in ROLES]
    roles = [role for role in roles if role]
    users = env['res.users'].with_context(active_test=False)
    if not officer or not roles:
        return users
    cr = env.cr
    cr.execute("SELECT gid, hid FROM res_groups_implied_rel")
    implied = defaultdict(set)
    for group_id, implied_id in cr.fetchall():
        implied[group_id].add(implied_id)
    skipped = frozenset((role.id, officer.id) for role in roles)
    if not any(edge[1] in implied.get(edge[0], ()) for edge in skipped):
        return users
    cr.execute("SELECT uid, gid FROM res_groups_users_rel")
    assigned = defaultdict(set)
    for user_id, group_id in cr.fetchall():
        assigned[user_id].add(group_id)
    affected = [
        user_id for user_id, group_ids in assigned.items()
        if officer.id in _closure(group_ids, implied)
        and officer.id not in _closure(group_ids, implied, skipped)
    ]
    return users.browse(sorted(affected))


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    officer = env.ref(HR_OFFICER, raise_if_not_found=False)
    roles = env['res.groups']
    for xmlid in ROLES:
        roles |= env.ref(xmlid, raise_if_not_found=False) or roles.browse()
    if not officer or not roles:
        return
    users = users_holding_officer_only_through_roles(env)
    if users:
        users.write({'group_ids': [Command.link(officer.id)]})
        _logger.info(
            "EH Attendance User and EH Attendance Auditor no longer imply HR "
            "Officer (%s). HR Officer was given explicitly to the %d user(s) "
            "who held it only through those roles, so no access is lost on "
            "upgrade; review these logins and revoke HR Officer where it is "
            "not needed: %s",
            HR_OFFICER, len(users), ', '.join(users.sorted('login').mapped('login')))
    else:
        _logger.info(
            "EH Attendance User and EH Attendance Auditor no longer imply HR "
            "Officer (%s); no user held it only through those roles.", HR_OFFICER)
    roles.filtered(lambda role: officer in role.implied_ids).write(
        {'implied_ids': [Command.unlink(officer.id)]})
    # The translated descriptions of both roles still say they imply HR User,
    # and an update rewrites only the English source. Keep the English text
    # alone; the module data then replaces it with the new description.
    roles.flush_recordset(['comment'])
    cr.execute(
        "UPDATE res_groups SET comment = jsonb_build_object('en_US', comment->>'en_US')"
        " WHERE id IN %s AND comment IS NOT NULL",
        [tuple(roles.ids)])
    roles.invalidate_recordset(['comment'])
