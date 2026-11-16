# -*- coding: utf-8 -*-
{
    'name': 'Dental Pharmacy - Point of Sale',
    'version': '20.0.1.1.0',
    'category': 'Healthcare/Dental',
    'summary': 'Dispense and bill doctor prescriptions at a Point of Sale pharmacy counter',
    'description': """
Connects the Dental Pharmacy with the Point of Sale.

* "Send to Pharmacy" on the consultation's Prescriptions tab puts the prescription in the
  counter's queue when the branch dispenses at the Point of Sale.
* Each clinic branch (company) chooses its dispensing mode: the pharmacy app's dispense form
  (default, unchanged behaviour) or a Point of Sale pharmacy counter.
* At a pharmacy counter the pharmacist loads the patient's pending prescriptions, sees the
  allergy alert, dosage instructions and medicine history, and sells with earliest-expiry
  batches. Expired batches are refused.
* Every pharmacy counter order is invoiced (walk-in sales go to a default walk-in customer).
* Paid orders create the pharmacy dispense record and update the prescription automatically,
  so the pharmacy dashboard, history and reports keep working. Refunds reverse it.
    """,
    'author': 'Hudson Software Solutions',
    'license': 'LGPL-3',
    'depends': [
        'dental_pharmacy',
        'point_of_sale',
        'pos_stock',
    ],
    'data': [
        'security/ir.access.csv',
        'data/res_partner_data.xml',
        'views/res_config_settings_views.xml',
        'views/pos_config_views.xml',
        'views/dental_pharmacy_dispense_views.xml',
        'views/dental_prescription_views.xml',
        'views/res_company_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'dental_pharmacy_pos/static/src/app/**/*',
        ],
        'web.assets_tests': [
            'dental_pharmacy_pos/static/tests/tours/**/*',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': True,
}
