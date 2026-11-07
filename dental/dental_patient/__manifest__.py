{
    'name': 'Dental Patient',
    'version': '20.0.1.0.0',
    'summary': 'Dental Patient management extending Contacts',
    'category': 'Dental Clinic',
    'author': 'Hudson Software Solutions',
    'depends': ['dental_base', 'contacts'],
    'data': [
        'data/sequence_data.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': ['dental_base'],
    'license': 'LGPL-3',
}
