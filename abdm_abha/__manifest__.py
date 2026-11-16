{
    'name': 'ABDM - ABHA Registration & Verification',
    'version': '20.0.1.0.1',
    'category': 'Healthcare',
    'summary': 'Create or verify a patient ABHA (Ayushman Bharat Health Account) '
               'with Aadhaar or mobile OTP and link it to the contact',
    'description': """
ABHA for any Odoo contact
=========================
Front-desk wizard with three paths:

* Verify an existing ABHA number (Aadhaar OTP or ABHA mobile OTP)
* Find a patient's ABHA by mobile number, then verify with OTP
* Create a new ABHA with Aadhaar OTP (consent captured), verify the
  communication mobile and choose an ABHA address

The verified ABHA number, address, KYC status and ABHA card are stored on the
contact. One ABHA number can belong to one contact only. Aadhaar numbers and
OTPs are never stored.
    """,
    'author': 'Hudson Software Solutions',
    'depends': ['abdm_base', 'contacts'],
    'data': [
        'security/ir.access.csv',
        'wizard/abdm_abha_wizard_views.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
