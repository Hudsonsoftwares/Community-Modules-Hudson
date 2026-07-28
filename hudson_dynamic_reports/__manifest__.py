# -*- coding: utf-8 -*-
{
    'name': 'Hudson Dynamic Reports',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Interactive Dynamic Financial Reports for Odoo 19',
    'description': """
        Adds interactive web views for Profit and Loss, Balance Sheet, and Tax Reports.
        Uses OWL (Odoo Web Library) to render dynamic tables.
    """,
    'author': 'Hudson',
    'depends': ['om_account_accountant', 'om_account_daily_reports'],
    'data': [
        'security/ir.model.access.csv',
        'views/html_reports_views.xml',
        'views/dynamic_report_action.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hudson_dynamic_reports/static/src/scss/dynamic_report.scss',
            'hudson_dynamic_reports/static/src/js/dynamic_report.js',
            'hudson_dynamic_reports/static/src/xml/dynamic_report.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
