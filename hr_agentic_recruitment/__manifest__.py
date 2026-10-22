{
    'name': 'Agentic AI Recruitment (Odoo 20)',
    'version': '20.0.1.0.0',
    'category': 'Human Resources/Recruitment',
    'summary': 'AI-powered resume screening and candidate ranking.',
    'description': """
        Integrates Agentic AI (OpenAI/Gemini) to automatically screen applicant resumes.
        - Adds AI Match Score.
        - Adds AI Summary.
        - Configurable via Settings.
    """,
    'depends': ['hr_recruitment', 'base_setup'],
    'data': [
        'views/res_config_settings_views.xml',
        'views/hr_applicant_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
