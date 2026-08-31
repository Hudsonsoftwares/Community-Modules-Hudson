# -*- coding: utf-8 -*-
{
    'name': 'Helpdesk Pro',
    'version': '1.1',
    'category': 'Services/Helpdesk',
    'summary': 'Advanced Helpdesk Management Pro',
    'description': """
        Standalone Helpdesk Management application for Odoo.
        Provides ticketing, SLA management, teams, and customer portal.
    """,
    'author': 'Antigravity',
    'website': 'https://www.example.com',
    'depends': ['base', 'mail', 'portal', 'website', 'resource', 'im_livechat', 'website_forum', 'knowledge_management_pro', 'sale_management', 'account', 'stock', 'loyalty', 'repair', 'project', 'hudson_field_service'],
    'data': [
        'security/helpdesk_security.xml',
        'security/ir.model.access.csv',
        'wizard/ticket_after_sales_wizard_views.xml',
        'data/helpdesk_data.xml',
        'data/mail_template_data.xml',
        'views/helpdesk_menu_views.xml',
        'views/helpdesk_ticket_views.xml',
        'views/helpdesk_stage_views.xml',
        'views/helpdesk_team_views.xml',
        'views/helpdesk_category_views.xml',
        'views/helpdesk_sla_views.xml',
        'views/helpdesk_reporting_views.xml',
        'views/helpdesk_portal_templates.xml',
        'views/project_task_views.xml',
        'views/field_service_order_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'helpdesk_management_pro/static/src/dashboard/helpdesk_dashboard.js',
            'helpdesk_management_pro/static/src/dashboard/helpdesk_dashboard.xml',
            'helpdesk_management_pro/static/src/dashboard/helpdesk_dashboard.scss',
        ],
    },
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
