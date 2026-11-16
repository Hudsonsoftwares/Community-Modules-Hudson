# -*- coding: utf-8 -*-
{
    'name': 'Dental Patient Education & Video Library',
    'version': '20.0.1.0.0',
    'category': 'Healthcare/Dental',
    'summary': 'Treatment education videos, 3D animations and post-care media stored in the existing '
               'Document Management System, presented to patients on clinic monitors and tablets',
    'description': """
Patient Treatment Education & Video Library
===========================================
* Library = DMS files in "Dental Hospital / Patient Education Library / <Topic>" folders
  (no separate media storage). Topics are DMS categories (Braces, Root Canal, Implants,
  Extraction, Whitening, Crowns ...) linked to dental treatments for recommendations.
* Media metadata on the DMS file: media type (video, 3D animation, image, leaflet),
  purpose (before treatment, procedure, post-treatment care), language and language
  variants of the same video, thumbnail (DMS file image).
* Education sessions per patient (from a consultation, case, treatment plan or session):
  treatment-specific recommendations in the patient's language, dentist preview,
  full-screen presentation on a clinic monitor or tablet through an expiring secure link,
  viewing history and patient acknowledgement.
""",
    'author': 'Hudson Softwares',
    'license': 'LGPL-3',
    'depends': ['dental_dms'],
    'data': [
        'security/ir.access.csv',
        'data/ir_sequence_data.xml',
        'data/education_topic_data.xml',
        'views/dms_file_views.xml',
        'views/dms_category_views.xml',
        'views/dental_education_session_views.xml',
        'views/dental_education_media_wizard_views.xml',
        'views/dental_record_views.xml',
        'views/education_presenter_templates.xml',
        'views/dental_education_menus.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'auto_install': True,
    'installable': True,
    'application': False,
}
