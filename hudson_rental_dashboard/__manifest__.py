# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

{
    'name': 'Hudson Rental Dashboard',
    'version': '20.0.1.1.0',
    'category': 'Productivity/Dashboard',
    'summary': 'Rental dashboard in the Dashboards app',
    'description': """
Rental dashboard in the Dashboards app, next to the Sales dashboards: quotations, rentals and revenue with their
trend, daily rentals, and the top categories, products, salespeople and customers of the rental orders.

Installed with the Rental app, like the dashboards of Odoo Online.
    """,
    'author': 'Hudson Community',
    'depends': ['spreadsheet_dashboard', 'hudson_rental'],
    'data': [
        'data/dashboards.xml',
    ],
    'auto_install': ['hudson_rental'],
    'license': 'LGPL-3',
}
