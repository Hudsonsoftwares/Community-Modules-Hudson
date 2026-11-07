# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

{
    'name': 'Hudson Subscription Dashboard',
    'version': '20.0.1.0.0',
    'category': 'Productivity/Dashboard',
    'summary': 'Subscription dashboards in the Dashboards app',
    'description': """
Subscription dashboards in the Dashboards app, designed like the ones of Odoo Online:

- Subscriptions: MRR and ARR, subscriptions, customer lifespan and lifetime value; MRR by
  category, recurrence, country and sales team, and the top quotations, subscriptions, plans,
  products, sales teams, salespeople, recurrences and countries.
- MRR Evolution: new MRR, up/downgrades, churn, net new MRR and non recurring invoiced; MRR over
  time and its breakdown, top upgrades, worst downgrades, and MRR by recurrence, team,
  salesperson and country.
- Retention: customer and revenue churn rates, net retention and customer lifetime value, month
  by month.
- Salesperson: new subscriptions, churn, MRR evolution and non recurring revenue of the current
  user, with their best and worst subscriptions.

The MRR changes (new, expansion, contraction, churn) are derived from the subscriptions, their
upsells and renewals, like the subscription logs of Odoo Enterprise.

Installed with Hudson Subscriptions, like the dashboards of Odoo Online.
    """,
    'author': 'Hudson Community',
    'depends': ['spreadsheet_dashboard', 'hudson_subscriptions'],
    'data': [
        'security/ir.access.csv',
        'data/dashboards.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': ['hudson_subscriptions'],
    'license': 'LGPL-3',
}
