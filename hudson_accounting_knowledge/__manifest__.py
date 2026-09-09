# -*- coding: utf-8 -*-
{
    'name': 'Hudson Accounting Knowledge Integration',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': 'Insert Accounting Reports into Knowledge Articles',
    'author': 'Hudson Softwares',
    'website': 'https://hudsonsoftwares.com',
    'license': 'LGPL-3',
    'depends': [
        'hudson_accounting_enhancements',
        'knowledge_management_pro',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/hudson_report_export_knowledge_wizard_views.xml',
    ],
    'installable': True,
    'auto_install': True,
}
