{
    'name': 'Hudson Sign',
    'version': '20.0.1.0.0',
    'summary': 'Dedicated module for document signatures',
    'category': 'Document Management',
    'author': 'Hudson Softwares',
    'depends': [
        'dms',
        'dms_enterprise_features',
        'mail', 
        'portal', 
        'web'
    ],
    'data': [
        'security/ir.access.csv',
        'data/hudson_sign_item_type_data.xml',
        'views/hudson_sign_template_views.xml',
        'views/hudson_sign_template_tag_views.xml',
        'views/hudson_sign_menus.xml',
        'views/hudson_sign_request_views.xml',
        'views/hudson_sign_item_type_views.xml',
        'views/hudson_sign_reports_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hudson_sign/static/src/css/green_savings.css',
            'hudson_sign/static/src/css/template_kanban.css',
            'hudson_sign/static/src/js/green_savings.js',
            'hudson_sign/static/src/xml/green_savings.xml',
            'hudson_sign/static/src/js/template_builder.js',
            'hudson_sign/static/src/xml/template_builder.xml',
            'hudson_sign/static/src/js/template_view_buttons.js',
            'hudson_sign/static/src/xml/template_view_buttons.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
