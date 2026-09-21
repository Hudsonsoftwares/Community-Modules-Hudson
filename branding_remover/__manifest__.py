# -*- coding: utf-8 -*-
{
    'name': 'Branding Remover',
    'version': '19.0.1.0.0',
    'category': 'Technical',
    'summary': 'Remove Odoo branding from invoices, receipts, and the user interface',
    'description': """
Branding Remover
================
This module removes Odoo branding elements from the following locations:

* "Powered by Odoo" footer on PDF invoices and portal pages
* "Powered by Odoo" badge on Point of Sale receipts and the customer display screen
* Odoo logo (the "O") overlaid on QR codes in invoice PDF reports
* "My Odoo.com Account" option from the user profile dropdown menu
* "Powered by Odoo" link on the database login / authentication page

**What is NOT removed:**
- Copyright and license notices embedded in source-code files
- Odoo copyright notices required by the applicable open-source licence (LGPL-3)
    """,
    'author': 'Hudson Softwares',
    'website': 'https://www.hudsonsoftwares.com',
    'license': 'LGPL-3',
    'depends': [
        'web',
        'portal',
        'account',
        'point_of_sale',
        'hr_attendance',
    ],
    'data': [
        'views/branding_remover_templates.xml',
    ],
    'assets': {
        # Backend user menu & webclient branding
        'web.assets_backend': [
            'branding_remover/static/src/js/remove_odoo_account_menu.js',
        ],
        # POS receipt / customer-display branding
        'point_of_sale.assets': [
            'branding_remover/static/src/xml/pos_receipt_patch.xml',
            'branding_remover/static/src/xml/pos_customer_display_patch.xml',
        ],
        # HR Attendance kiosk mode branding
        'hr_attendance.assets_public_attendance': [
            'branding_remover/static/src/xml/kiosk_patch.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
