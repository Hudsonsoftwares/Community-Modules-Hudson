{
    'name': 'Appraisals',
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Employee Appraisals and Goals Management',
    'description': """
        Custom Appraisals module matching specific Kanban view layout.
        Features: Appraisals, Goals, Launch Campaign.
    """,
    'author': 'Antigravity',
    'depends': ['hr', 'mail', 'survey', 'hr_skills'],
    'data': [
        'security/hr_appraisal_security.xml',
        'security/ir.model.access.csv',
        'data/hr_appraisal_cron.xml',
        'wizard/appraisal_launch_wizard_views.xml',
        'views/hr_appraisal_goal_template_views.xml',
        'views/hr_appraisal_goal_views.xml',
        'views/hr_appraisal_template_views.xml',
        'views/hr_appraisal_views.xml',
        'views/res_config_settings_views.xml',
        'views/hr_appraisal_scale_views.xml',
        'views/hr_appraisal_goal_tag_views.xml',
        'views/mail_activity_views.xml',
        'views/hr_appraisal_report_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
