# -*- coding: utf-8 -*-
# Part of Hudson. See LICENSE file for full copyright and licensing details.

{
    'name': 'Hudson Rental Management',
    'version': '19.0.1.0.0',
    'category': 'Sales/Rental',
    'sequence': 60,
    'summary': 'Rent products to customers with flexible pricing and scheduling',
    'description': """
Hudson Rental Management
========================

Complete rental management solution for renting products to customers:

* **Product Rental Configuration** - Mark products as rentable with flexible pricing
* **Rental Pricing** - Define hourly, daily, weekly, monthly pricing tiers
* **Online Rental** - Customers can rent products directly from website
* **Rental Orders** - Full lifecycle management from pickup to return
* **Stock Management** - Track rental stock availability in real-time
* **Late Fee Management** - Automatic calculation of late fees
* **Rental Status Tracking** - Track pickup, in-use, returned status
* **Invoicing** - Generate invoices based on actual rental duration
* **Reports & Analytics** - Comprehensive rental analytics
* **Portal Access** - Customer portal for rental history
    """,
    'author': 'Hudson Community',
    'website': 'https://github.com/nandusaji2001/hudson-community',
    'depends': [
        'base',
        'web',
        'sale_management',
        'sale_stock',
        'stock',
        'product',
        'account',
        'portal',
        'website_sale',
    ],
    'data': [
        # Security
        'security/rental_security.xml',
        'security/ir.model.access.csv',
        
        # Data
        'data/rental_sequence.xml',
        'data/rental_status_data.xml',
        'data/rental_pricing_data.xml',
        'data/rental_mail_template.xml',
        
        # Views
        'views/product_template_views.xml',
        'views/rental_order_views.xml',
        'views/rental_pricing_views.xml',
        'views/rental_order_line_views.xml',
        'views/sale_order_views.xml',
        'views/res_config_settings_views.xml',
        # Website
        'views/rental_portal_templates.xml',
        'views/rental_website_templates.xml',
        
        # Wizard
        'wizard/rental_return_wizard_views.xml',
        'wizard/rental_extend_wizard_views.xml',
        'wizard/rental_pickup_wizard_views.xml',
        
        # Reports
        'report/rental_report_views.xml',
        'report/rental_report_templates.xml',
        
        # Menus (must be loaded last after all actions are defined)
        'views/rental_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hudson_rental/static/src/js/rental_calendar.js',
            'hudson_rental/static/src/xml/rental_calendar.xml',
            'hudson_rental/static/src/css/rental_backend.css',
        ],
        'web.assets_frontend': [
            'hudson_rental/static/src/js/rental_configurator.js',
            'hudson_rental/static/src/js/rental_portal.js',
            'hudson_rental/static/src/css/rental_frontend.css',
        ],
    },
    'demo': [
        'data/rental_demo_data.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
