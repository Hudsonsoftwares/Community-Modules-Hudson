# -*- coding: utf-8 -*-
{
    'name': 'Dental Documents - Pharmacy',
    'version': '20.0.1.0.0',
    'category': 'Healthcare/Dental',
    'summary': 'Files prescriptions and pharmacy dispensing documents in the DMS, patient-wise',
    'author': 'Hudson Softwares',
    'license': 'LGPL-3',
    'depends': ['dental_dms', 'dental_pharmacy'],
    'data': [
        'security/dental_dms_pharmacy_access_groups.xml',
        'views/dental_pharmacy_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'auto_install': True,
    'installable': True,
}
