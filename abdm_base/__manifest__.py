{
    'name': 'ABDM Base (Ayushman Bharat Digital Mission)',
    'version': '20.0.1.3.0',
    'category': 'Healthcare',
    'summary': 'Connection to the ABDM gateway: credentials, session tokens, '
               'callbacks, request tracking and API audit log',
    'description': """
ABDM Base
=========
Generic, specialty-independent foundation for ABDM integration.
Vertical modules (e.g. dental_abdm) build ABHA, Scan & Share, HIP and HIU
flows on top of it.

* Settings: environment (sandbox / production), client ID and secret,
  public callback URL, facility (HFR) ID per company
* Gateway client with cached session token and automatic refresh
* Test Connection, Register Bridge URL and Linked Services actions
* Callback receiver for the ABDM V3 asynchronous APIs (/api/v3/...)
  with optional gateway signature check
* Transactions: tracks every asynchronous request until ABDM answers
* API log with masked secrets / OTPs / Aadhaar and automatic clean-up
    """,
    'author': 'Hudson Software Solutions',
    'depends': ['base', 'mail'],
    'external_dependencies': {'python': ['requests', 'cryptography']},
    'data': [
        'security/abdm_security.xml',
        'security/ir.access.csv',
        'data/ir_cron_data.xml',
        'views/abdm_api_log_views.xml',
        'views/abdm_transaction_views.xml',
        'views/res_config_settings_views.xml',
        'views/abdm_menus.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
