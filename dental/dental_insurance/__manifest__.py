{
    'name': 'Dental Insurance',
    'version': '20.0.1.0.0',
    'category': 'Dental Clinic',
    'summary': 'Insurance for the dental clinic: patient policies and dental coverage rules',
    'description': """
Dental Insurance
================
Piece 1:

* "Insurance" tab on the dental patient form (policies, validity, eligibility check)
* Coverage rules per dental treatment category (e.g. Endodontics 80 %)
* Insurance companies, TPAs and plans under Dental Clinic > Configuration
* Reception, assistant and dentist roles can record policies; managers set up plans

Later pieces add estimates on treatment plans, pre-authorization,
split invoices (patient share / insurer share) and claims.
    """,
    'author': 'Hudson Software Solutions',
    'depends': ['insurance_base', 'dental_patient', 'dental_catalog'],
    'data': [
        'data/dental_insurance_security.xml',
        'views/insurance_plan_views.xml',
        'views/res_partner_views.xml',
        'views/dental_insurance_menus.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
