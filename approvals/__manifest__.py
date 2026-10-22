# -*- coding: utf-8 -*-
{
    'name': 'Approvals',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Approvals',
    'summary': 'Manage approval requests: purchases, expenses, access, and more',
    'description': """
Approvals Management
=====================
Create and manage approval requests for anything: purchases, contracts,
access requests, cash advances, and more.

Features
--------
* Configurable Approval Categories (request types) with custom approver rules
* Sequential or "any approver" approval flows
* Product / amount lines per request
* Attachments & chatter/activity tracking
* My Requests / To Approve / All Requests dashboards
* Automatic activities & notifications for approvers
    """,
    'author': 'Custom Development',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'product', 'web', 'account', 'purchase'],
    'data': [
        'security/approval_security.xml',
        'security/ir.access.csv',
        'data/approval_category_data.xml',
        'data/mail_activity_data.xml',
        'data/ir_sequence_data.xml',
        'wizard/approval_refuse_wizard_views.xml',
        'views/approval_category_views.xml',
        'views/approval_request_views.xml',
        'views/approval_product_line_views.xml',
        'views/approval_menus.xml',
    ],
    'demo': [
        'data/approval_demo.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
