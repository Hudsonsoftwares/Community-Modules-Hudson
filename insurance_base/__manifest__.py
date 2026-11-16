{
    'name': 'Insurance (Healthcare)',
    'version': '20.0.1.0.0',
    'category': 'Healthcare',
    'summary': 'Patient insurance for any clinic: insurers, TPAs, plans, coverage rules, '
               'policies and eligibility checks',
    'description': """
Insurance Base
==============
Specialty-independent health insurance. Dental, eye, physiotherapy... modules
add their own coverage rules and screens on top of it; connectors (e.g.
``abdm_nhcx`` for India's National Health Claims Exchange) plug into the
eligibility check.

* Insurance companies and TPAs (contacts with an insurance role and the
  connector used to reach them)
* Plans with coverage rules: by service, by product category or for everything,
  with coverage %, per-service limit and pre-authorization flag
* Patient policies: member ID, policy number, policyholder and relationship,
  validity, sum insured, insurance card
* Eligibility checks: one record per check with the payer's answer (in force,
  benefit balances: allowed / used / remaining). Manual connector for payers
  that are not connected: staff record what the payer said by phone or portal.
    """,
    'author': 'Hudson Software Solutions',
    'depends': ['contacts', 'product', 'mail'],
    'data': [
        'security/insurance_security.xml',
        'security/ir.access.csv',
        'views/insurance_plan_views.xml',
        'views/insurance_eligibility_views.xml',
        'views/insurance_policy_views.xml',
        'views/res_partner_views.xml',
        'views/insurance_menus.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
