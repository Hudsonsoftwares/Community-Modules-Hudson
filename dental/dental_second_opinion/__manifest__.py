# -*- coding: utf-8 -*-
{
    'name': 'Dental Clinical Second Opinion',
    'version': '20.0.1.0.1',
    'category': 'Healthcare/Dental',
    'summary': 'Refer complex dental cases to specialists for review, findings, recommendations and a recorded clinical decision',
    'description': """
Clinical Second Opinion Workflow
================================
Optional add-on. The dental suite works unchanged without it.

* A dentist refers a dental case to a specialist, sharing the case's consultations,
  diagnoses, X-rays / patient documents and (for reference only) a treatment plan.
* The specialist reviews the shared clinical records and submits findings,
  recommendations and attachments, or asks the requesting dentist for more information.
* The requesting dentist is notified, then records the final clinical decision or requests clarification.
* Treatment plans are never modified automatically; the dentist updates them in the clinical workflow.

Reuses existing records: patients (res.partner), dentists (hr.employee), dental cases,
clinical examinations, diagnoses, treatment plans and patient documents / X-rays.

Includes request tracking, a specialist dashboard, workflow statuses, chatter notifications and
activities, an append-only audit history, role-based access and branch (multi-company) isolation
following dental_base/SECURITY.md.
    """,
    'author': 'Hudson Software Solutions',
    'license': 'LGPL-3',
    'depends': [
        'mail',
        'dental_base',
        'dental_patient',
        'dental_core',
    ],
    'data': [
        'security/dental_second_opinion_security.xml',
        'security/ir.access.csv',
        'data/dental_second_opinion_data.xml',
        'wizard/dental_second_opinion_wizard_views.xml',
        'views/dental_second_opinion_views.xml',
        'views/dental_case_views_inherit.xml',
        'views/dental_second_opinion_dashboard_views.xml',
        'views/dental_second_opinion_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dental_second_opinion/static/src/scss/second_opinion_dashboard.scss',
            'dental_second_opinion/static/src/js/second_opinion_dashboard.js',
            'dental_second_opinion/static/src/xml/second_opinion_dashboard.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
