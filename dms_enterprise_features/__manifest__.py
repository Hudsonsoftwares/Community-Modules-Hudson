# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).
{
    "name": "DMS Enterprise Features — Files Centralization & Auto-Assignment",
    "summary": """
        Adds enterprise-grade Files Centralization with automatic document
        routing to folders for HR, Recruitment, Accounting, Products,
        Projects, Approvals and Sign modules.
    """,
    "version": "19.0.1.0.0",
    "category": "Document Management",
    "license": "LGPL-3",
    "author": "Hudson Community",
    "website": "https://github.com/nandusaji2001/hudson-community",
    "depends": [
        "dms",
        "mail",
        "base_setup",
        "hr",
        "portal",
        "fleet",
    ],
    "data": [
        # Security
        "security/security.xml",
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        # Data (must be before views so default folders exist)
        "data/res_groups_privilege.xml",
        "data/dms_sequence.xml",
        "data/default_dms_storage.xml",
        "data/default_dms_directories.xml",
        "data/default_folder_rules.xml",
        "data/mail_template_data.xml",
        "data/dms_cron.xml",
        # Views
        "views/dms_menu.xml",

        "views/dms_folder_rule_views.xml",
        "views/dms_access_groups_views.xml",
        "views/res_config_settings.xml",
        "views/dms_file_views.xml",
        "views/dms_directory_views.xml",
        "views/dms_approval_views.xml",
        "views/dms_signature_views.xml",
        "views/dms_my_documents_views.xml",
        "views/dms_file_log_views.xml",
        "views/dms_signature_setup_templates.xml",
        "views/dms_portal_templates.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "dms_enterprise_features/static/src/js/signature_client_action.js",
            "dms_enterprise_features/static/src/xml/signature_client_action.xml",
            "dms_enterprise_features/static/src/js/search_panel_trash.js",
            "dms_enterprise_features/static/src/xml/search_panel_trash.xml",
        ],
    },
    "application": True,
    "installable": True,
    "auto_install": False,
    "post_init_hook": "post_init_hook",
    "icon": "/dms/static/description/icon.png",
}
