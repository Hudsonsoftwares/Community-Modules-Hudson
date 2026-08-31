# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

{
    'name': 'Planning',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Planning',
    'sequence': 56,
    'summary': 'Manage shifts, planning roles, and assignments',
    'description': """
Planning Management
===================

A planning management module for Odoo 19 that provides:
* **Shift Management** - Plan and assign shifts to employees.
* **Planning Roles** - Define roles for shift assignments.
* **Attendance Integration** - Link shifts to attendance records.
    """,
    'website': 'https://github.com/nandusaji2001/hudson-community',
    'author': 'Hudson Community',
    'depends': [
        'hr',
        'hr_attendance',
        'mail',
        'project',
        'sale',
        'web',
    ],
    'data': [
        'security/planning_security.xml',
        'security/ir.model.access.csv',
        'data/fs_planning_role_data.xml',
        'wizard/fs_shift_template_apply_wizard_views.xml',
        'wizard/fs_shift_confirm_wizard_views.xml',
        'views/fs_planning_slot_views.xml',
        'views/fs_planning_role_views.xml',
        'views/fs_shift_template_views.xml',
        'views/field_service_planning_board_views.xml',
        'views/planning_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hudson_planning/static/src/css/fs_planning_board.css',
            'hudson_planning/static/src/js/fs_planning_board.js',
            'hudson_planning/static/src/xml/fs_planning_board.xml',
            'hudson_planning/static/src/css/fs_planning_schedule.css',
            'hudson_planning/static/src/js/fs_planning_schedule.js',
            'hudson_planning/static/src/xml/fs_planning_schedule.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
