# -*- coding: utf-8 -*-
{
    'name': 'Dental Treatment Consent & Signatures',
    'version': '20.0.1.0.0',
    'category': 'Healthcare/Dental',
    'summary': 'Electronic patient consent signing integrated with Treatment Plans and Hudson Sign',
    'description': """
Dental Treatment Consent & Signatures
=====================================
* Integrates Hudson Sign with Dental Treatment Plans.
* Generates clinical consent forms per treatment (Dental Implant, RCT, Extraction, Crown, etc.).
* Provides 'Sign Now' and 'Send Consent Request' directly on treatment plans.
* Automatically creates default professional consent templates with signer roles (Patient, Doctor) and signature boxes.
* Tracks consent status, signed document revisions, and chatter logs.
    """,
    'author': 'Hudson Softwares',
    'license': 'LGPL-3',
    'depends': [
        'dental_core',
        'dental_dms',
        'hudson_sign',
    ],
    'data': [
        'security/ir.access.csv',
        'wizard/dental_consent_wizard_views.xml',
        'views/dental_treatment_plan_views.xml',
        'views/product_template_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            ('include', 'web.chartjs_lib'),
            'dental_sign/static/src/js/chart_safety.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
