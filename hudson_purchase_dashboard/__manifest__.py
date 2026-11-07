# -*- coding: utf-8 -*-
{
    'name': 'Hudson Purchase Dashboard',
    'version': '20.0.2.0.0',
    'category': 'Productivity/Dashboard',
    'summary': 'Purchase dashboard in the Dashboards app',
    'description': """
Purchase dashboard in the Dashboards app, designed like the one of Odoo Online: purchased value,
orders, average order value, quantity ordered, days to confirm and receive, supplier service
level and on-time deliveries with their trend; purchased value over time, on-time deliveries and
lead time by vendor, average cost evolution, top purchase orders, late receipts, purchased
products and purchases by buyer.

Installed with Purchase and Inventory, like the dashboards of Odoo Online.
    """,
    'author': 'Hudson Community',
    'depends': ['spreadsheet_dashboard', 'purchase_stock'],
    'data': [
        'security/ir.access.csv',
        'data/dashboards.xml',
    ],
    'auto_install': ['purchase_stock'],
    'license': 'LGPL-3',
}
