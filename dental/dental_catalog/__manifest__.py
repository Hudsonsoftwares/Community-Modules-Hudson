{
    'name': 'Dental Catalog',
    'version': '1.1',
    'category': 'Healthcare/Dental',
    'summary': 'Dental Treatments and Catalog Management',
    'description': """
        Manage Dental Treatments using Odoo's product system.
        Adds dental-specific fields to products and organizes them into treatments.
    """,
    'author': 'Hudson Software Solutions',
    'depends': ['dental_base', 'product', 'sale'],
    'data': [
        'security/ir.access.csv',
        'views/dental_treatment_category_views.xml',
        'views/product_template_views.xml',
        'views/dental_catalog_menus.xml',
        'data/dental_treatment_data.xml',
        'views/dental_kanban_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': ['dental_base'],
    'license': 'LGPL-3',
}
