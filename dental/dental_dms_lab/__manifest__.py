# -*- coding: utf-8 -*-
{
    'name': 'Dental Documents - Laboratory',
    'version': '20.0.1.0.0',
    'category': 'Healthcare/Dental',
    'summary': 'Files lab orders, dispatch and receipt documents (impressions, scans, lab reports) in the DMS',
    'author': 'Hudson Softwares',
    'license': 'LGPL-3',
    'depends': ['dental_dms', 'dental_lab'],
    'data': [
        'security/dental_dms_lab_access_groups.xml',
        'views/dental_lab_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'auto_install': True,
    'installable': True,
}
