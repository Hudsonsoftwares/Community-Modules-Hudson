# -*- coding: utf-8 -*-
{
    'name': 'Hudson Knowledge',
    'version': '20.0.1.0.13',
    'category': 'Productivity/Knowledge',
    'summary': 'Create, share and manage knowledge articles with a rich text editor',
    'description': """
        Hudson Knowledge provides a full-featured knowledge base application:
        - Rich text articles with the native Odoo WYSIWYG editor
        - Sidebar with Favorites, Workspace, Shared and Private sections
        - Article hierarchy (parent/child tree)
        - Embedded Item Kanban, Item List and Item Calendar views inside articles
        - Article templates, cover images, icons and properties
        - Share articles with specific users
        - Lock content, Full-width mode, Move to Trash
    """,
    'author': 'Hudson Softwares',
    'website': 'https://hudsonsoftwares.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'web',
        'portal',
        'html_editor',
    ],
    'data': [
        'security/knowledge_security.xml',
        'security/ir.access.csv',
        'data/knowledge_data.xml',
        'views/knowledge_views.xml',
        'views/knowledge_item_views.xml',
        'views/knowledge_template_views.xml',
        'views/knowledge_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'web/static/src/core/emoji_picker/emoji_data.js',
            'hudson_knowledge/static/src/scss/knowledge.scss',
            'hudson_knowledge/static/src/xml/knowledge_templates.xml',
            'hudson_knowledge/static/src/js/knowledge_action.js',
            'hudson_knowledge/static/src/js/knowledge_wysiwyg_commands.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'icon': '/hudson_knowledge/static/description/icon.png',
}
