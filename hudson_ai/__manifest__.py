# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

{
    'name': 'Hudson AI Assistant',
    'version': '19.0.1.0.0',
    'category': 'Productivity/AI',
    'sequence': 10,
    'summary': 'Enterprise-grade AI assistant powered by local LM Studio — create records, query data, and get insights using natural language.',
    'description': """
Hudson AI Assistant
===================

Brings enterprise-level AI capabilities to Odoo Community edition using a
locally-hosted LM Studio model (Gemma, Llama, Qwen, etc.).

Features
--------
* **Natural Language Queries** — Ask questions like "Who is the most productive employee?"
* **Record Creation** — "Create a sales quotation for Azure Interior"
* **Record Updates** — "Mark all overdue tasks as high priority"
* **Cross-Module Awareness** — Searches across all installed Odoo modules
* **Chatter Summarize** — Summarize long message threads in one click
* **Draft with AI** — Generate email/note drafts from a simple instruction
* **Voice Input** — Speak your commands using the browser microphone
* **LM Studio Integration** — Works with any OpenAI-compatible local server
    """,
    'website': 'https://github.com/nandusaji2001/hudson-community',
    'author': 'Hudson Community',
    'depends': [
        'base',
        'mail',
        'web',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/hudson_ai_config_views.xml',
        'views/hudson_ai_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hudson_ai/static/src/scss/ai_assistant.scss',
            'hudson_ai/static/src/js/ai_assistant_panel.js',
            'hudson_ai/static/src/js/chatter_ai.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
