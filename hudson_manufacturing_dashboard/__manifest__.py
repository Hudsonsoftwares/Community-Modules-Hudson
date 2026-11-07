# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

{
    'name': 'Hudson Manufacturing Dashboard',
    'version': '20.0.2.0.0',
    'category': 'Productivity/Dashboard',
    'summary': 'Manufacturing dashboard in the Dashboards app',
    'description': """
Manufacturing dashboard in the Dashboards app, designed like the one of Odoo Online: manufacturing
orders, quantity produced, OEE and average cost per unit with their trend; weekly manufacturing
orders, quantity by product and status, and the top products, operation types and responsibles.

Installed with Manufacturing and its accounting (mrp_account, for the cost per unit), like the
dashboards of Odoo Online.
    """,
    'author': 'Hudson Community',
    'depends': ['spreadsheet_dashboard', 'mrp_account'],
    'data': [
        'data/dashboards.xml',
    ],
    'auto_install': ['mrp_account'],
    'license': 'LGPL-3',
}

