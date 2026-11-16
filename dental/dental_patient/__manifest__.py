{
    'name': 'Dental Patient',
    'version': '20.0.1.0.2',
    'summary': 'Dental Patient management extending Contacts',
    'category': 'Dental Clinic',
    'author': 'Hudson Software Solutions',
    'depends': ['dental_base', 'contacts'],
    'data': [
        'data/sequence_data.xml',
        'report/patient_id_card_reports.xml',
        'report/patient_id_card_report_templates.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': ['dental_base'],
    'license': 'LGPL-3',
}
