# -*- coding: utf-8 -*-
{
    'name': 'Dental Documents - Second Opinion',
    'version': '20.0.1.0.0',
    'category': 'Healthcare/Dental',
    'summary': 'Files second-opinion requests and specialist reports in the DMS, linked to the patient and case',
    'author': 'Hudson Softwares',
    'license': 'LGPL-3',
    'depends': ['dental_dms', 'dental_second_opinion'],
    'data': [
        'security/dental_dms_second_opinion_access_groups.xml',
        'views/dental_second_opinion_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'auto_install': True,
    'installable': True,
}
