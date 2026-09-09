{
    'name': 'Knowledge Management',
    'version': '19.0.1.0.9',
    'summary': 'Advanced Knowledge Management System with rich text editing, workspaces, and workflows.',
    'description': """
        A completely independent Knowledge Management module.
        Features include:
        - Workspaces
        - Articles with hierarchical support
        - Categories and Tags
        - Templates
        - Approvals
        - Comments and Sharing
    """,
    'category': 'Productivity',
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'depends': ['base', 'mail', 'web', 'portal', 'website'],
    'data': [
        'security/knowledge_security.xml',
        'security/ir.model.access.csv',
        'views/menu_views.xml',
        'wizard/article_move_wizard_views.xml',
        'views/workspace_views.xml',
        'views/article_views.xml',
        'views/category_views.xml',
        'views/tag_views.xml',
        'views/template_views.xml',
        'views/dashboard_views.xml',
        'views/portal_templates.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'knowledge_management_pro/static/src/css/style.css',
            'knowledge_management_pro/static/src/components/calendar_board.js',
            'knowledge_management_pro/static/src/components/list_mockup.js',
            'knowledge_management_pro/static/src/components/app.js',
            'knowledge_management_pro/static/src/components/sidebar.js',
            'knowledge_management_pro/static/src/components/editor.js',
            'knowledge_management_pro/static/src/components/systray_knowledge.js',
            'knowledge_management_pro/static/src/js/slash_commands.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
