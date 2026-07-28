# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

{
    'name': 'Social Media Marketing',
    'version': '19.0.1.0.0',
    'category': 'Marketing/Social Marketing',
    'sequence': 45,
    'summary': 'Manage and publish social media posts via Odoo Enterprise connector',
    'description': """
Social Media Marketing
======================

A comprehensive social media marketing module for Odoo Community that connects
to Odoo Enterprise (Social Marketing) via the external JSON-RPC API.

Features:
* **Social Accounts** — View all connected social media accounts from the remote instance
* **Posts Management** — Create, edit, schedule, and publish posts synced to Enterprise
* **Feed / Streams** — Monitor incoming engagement from connected social accounts
* **Dashboard** — Kanban-style overview with engagement metrics
* **Auto-Sync** — Periodic background sync (every 5 minutes) via scheduled action
* **Settings** — Configure remote URL, database, email, and API key
* **Bidirectional Sync** — Push local changes to remote and pull remote data locally
    """,
    'website': 'https://github.com/nandusaji2001/hudson-community',
    'author': 'Hudson Community',
    'depends': [
        'base',
        'mail',
        'base_setup',
    ],
    'data': [
        # Security (must be first)
        'security/hudson_social_security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/hudson_social_config_data.xml',
        'data/hudson_social_cron.xml',
        # Wizard
        'wizard/social_post_publish_wizard_views.xml',
        # Views
        'views/res_config_settings_views.xml',
        'views/social_account_views.xml',
        'views/social_post_views.xml',
        'views/social_stream_views.xml',
        'views/social_dashboard_views.xml',
        # Menus (last — references actions from views)
        'views/social_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hudson_social_marketing/static/src/css/hudson_social.css',
        ],
    },
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_hook',
}
