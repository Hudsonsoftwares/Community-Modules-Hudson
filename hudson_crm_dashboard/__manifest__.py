# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

{
    'name': 'Hudson CRM Dashboard',
    'version': '20.0.2.1.0',
    'category': 'Productivity/Dashboard',
    'summary': 'CRM dashboards in the Dashboards app',
    'description': """
CRM dashboards in the Dashboards app, designed like the ones of Odoo Online:

- Leads: close rate, average deal size, revenue, days to win and to assign with their trend; leads
  per month, campaigns, sources, and the top countries, tags, lost reasons, mediums, sales teams
  and salespeople.
- Pipeline: expected and closed revenue, opportunities to close; top opportunities, stage funnel,
  forecast by sales team, and the top countries, sources, cities, mediums, salespeople and teams.

Installed with the CRM app, like the dashboards of Odoo Online.
    """,
    'author': 'Hudson Community',
    'depends': ['spreadsheet_dashboard', 'crm'],
    'data': [
        'data/dashboards.xml',
    ],
    'auto_install': ['crm'],
    'license': 'LGPL-3',
}

