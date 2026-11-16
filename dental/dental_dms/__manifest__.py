# -*- coding: utf-8 -*-
{
    'name': 'Dental Documents (DMS Integration)',
    'version': '20.0.1.0.1',
    'category': 'Healthcare/Dental',
    'summary': 'Centralised patient, clinical, billing, staff and administrative documents '
               'for the dental hospital, built on the existing Document Management System',
    'description': """
Dental Documents - DMS Integration
==================================
Bridges the dental hospital modules with the existing Document Management System
(``dms`` + ``dms_enterprise_features``) without changing it:

* Attachments of patients, appointments, consultations, dental cases, odontogram findings,
  X-rays / imaging, treatment plans and sessions, consents, invoices, employees and purchase
  orders are filed automatically as ``dms.file`` records that *reference* the original
  attachment (no file copy, no second storage).
* Files already routed by a DMS folder rule are enriched with dental links instead of being
  filed twice.
* Patient-wise and record-wise smart buttons, an "Add Document" wizard and a central
  Dental Documents search.
* Role-based access through DMS access groups bound to the dental roles, branch (company)
  isolation and a patient-privacy rule mirroring access to the clinical record.
""",
    'author': 'Hudson Softwares',
    'license': 'LGPL-3',
    'depends': [
        'dms',
        'dms_enterprise_features',
        'dental_core',
        'account',
        'hr',
        'purchase',
    ],
    'data': [
        'security/dental_dms_access_groups.xml',
        'security/ir.access.csv',
        'views/dms_file_views.xml',
        'views/dental_dms_upload_wizard_views.xml',
        'views/dental_record_views.xml',
        'views/dental_dms_menus.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'auto_install': ['dental_core', 'dms'],
    'installable': True,
    'application': False,
}
