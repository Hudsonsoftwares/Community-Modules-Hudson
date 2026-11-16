# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

{
    'name': 'Hudson AI Assistant',
    'version': '20.0.2.1.1',
    'category': 'Productivity/AI',
    'sequence': 10,
    'summary': 'Ask questions about your data, create records and summarize discussions with AI (Groq, Gemini or any OpenAI-compatible API).',
    'description': """
Hudson AI Assistant
===================

* **Ask AI** button in the top bar: questions about your data in plain language
  ("sales this month", "overdue invoices per customer"), record creation and updates.
* **AI** button in every chatter: summarize the discussion, draft a reply, ask about the record.
* Works with Groq (free plan available), Google Gemini or any OpenAI-compatible
  server such as LM Studio. Configure it in Settings > Hudson AI.
* Data access: each user can only ask about data of the apps they can open
  (on top of Odoo access rights), plus admin Block / Allow rules per model and group.
* Usage report (tokens per user / feature) and an optional gateway: share one
  provider key with your clients' databases, each with its own key and
  monthly token / daily call limits.
    """,
    'website': 'https://github.com/nandusaji2001/hudson-community',
    'author': 'Hudson Community',
    'depends': [
        'base_setup',
        'mail',
    ],
    'data': [
        'security/ir.access.csv',
        'views/hudson_ai_views.xml',
        'views/res_config_settings_views.xml',
        'views/hudson_ai_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hudson_ai/static/src/scss/ai_assistant.scss',
            'hudson_ai/static/src/js/ai_panel.js',
            'hudson_ai/static/src/js/ai_systray.js',
            'hudson_ai/static/src/xml/ai_systray.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
