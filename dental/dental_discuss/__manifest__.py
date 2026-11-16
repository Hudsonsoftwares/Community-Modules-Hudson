# -*- coding: utf-8 -*-
{
    'name': 'Dental Clinic Management - Discuss & Clinical Communication',
    'version': '20.0.1.0.0',
    'category': 'Healthcare/Dental',
    'summary': 'Odoo Discuss integration for Dental Hospital: Dentist consultations, Front-Desk alerts, Lab & Pharmacy chats, Department channels, and PHI protection',
    'description': """
Dental Clinic Discuss & Communication Integration
=================================================
Seamlessly integrates native Odoo Discuss into the Dental Hospital ERP suite
without altering core mail or discuss behavior.

Key Features:
-------------
* **Dentist-to-Dentist Clinical Consultations**:
  - Secure peer discussions on dental cases, treatment options, and complex pathologies.
  - Linked directly to dental cases, patient history, and clinical examinations.
  - 1-click posting of clinical consensus/decisions directly to record chatter.

* **Receptionist-to-Doctor Coordination**:
  - Instant front-desk alerts to chairside dentists (patient checked in, chair prepped, patient running late, emergencies).
  - Automated Discuss notifications triggered on patient check-in with token number and visit details.

* **Pharmacy & Laboratory Discussions**:
  - Prescribing dentist and dispensing pharmacist discussions on drug substitutions, allergies, and dosages.
  - Direct coordination between dental laboratory technicians and dentists on crown/bridge impressions, shade matching, and rework alerts.

* **Specialist Referrals**:
  - Integrated with Clinical Second Opinions & referrals (`dental.second.opinion`).
  - Automated referral channel creation and real-time alerts to consulting specialists.

* **Department Channels**:
  - Pre-configured, categorized channels for Orthodontics, Endodontics, Oral Surgery, Periodontics, Prosthodontics, Pedodontics, Front Desk, Pharmacy, and Lab.

* **Administrative Announcements**:
  - Read-only clinic-wide broadcasts restricted to Clinic Managers and Dental Administrators for hospital policies and updates.

* **Confidentiality, PHI Protection & Multi-Company Security**:
  - Role-based channel authorization separating clinical discussions from non-clinical personnel.
  - Strict branch-level isolation (`company_id`) matching the dental suite multi-company security standard.
  - Full audit logging on record chatters.
    """,
    'author': 'Hudson Software Solutions',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'dental_base',
        'dental_appointment',
        'dental_core',
        'dental_lab',
        'dental_pharmacy',
        'dental_second_opinion',
    ],
    'data': [
        'security/dental_discuss_security.xml',
        'security/ir.access.csv',
        'data/discuss_channel_data.xml',
        'wizard/dental_reception_alert_wizard_views.xml',
        'wizard/dental_case_discuss_wizard_views.xml',
        'wizard/dental_log_chatter_wizard_views.xml',
        'views/discuss_channel_views.xml',
        'views/dental_appointment_views_inherit.xml',
        'views/dental_case_views_inherit.xml',
        'views/dental_lab_order_views_inherit.xml',
        'views/dental_prescription_views_inherit.xml',
        'views/dental_second_opinion_views_inherit.xml',
        'views/dental_discuss_menus.xml',
    ],
    'demo': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}

