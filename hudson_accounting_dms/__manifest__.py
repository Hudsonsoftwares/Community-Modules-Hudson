# -*- coding: utf-8 -*-
{
    'name': 'Hudson Accounting DMS Integration',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': 'Export Accounting Reports to DMS Documents',
    'author': 'Hudson Softwares',
    'website': 'https://hudsonsoftwares.com',
    'license': 'LGPL-3',
    'depends': [
        'hudson_accounting_enhancements',
        'dms',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/hudson_report_export_dms_wizard_views.xml',
    ],
    'installable': True,
    'auto_install': True,
}
