{
    'name': 'Dental Treatment Board (Project & Sales)',
    'version': '1.1.0',
    'category': 'Healthcare/Dental',
    'summary': 'Treatment plans as projects: every phase of a plan is a task on its board, billed through one quotation',
    'author': 'Hudson Software Solutions',
    'description': """
Dental Treatment Board
======================
Connects dental treatment plans to Project and Sales:

- Each treatment plan is a project; each task of the project is one phase of the plan
  (e.g. "Phase 1 · Pain relief"), with the treatments done in it.
- "New Plan" on a case opens the plan's board straight away: columns Planned, In Progress, Done.
  A phase moves to In Progress at its first visit and to Done once all its treatments are done;
  dragging it to Done records the remaining visits, cancelling it declines its treatments.
- Accepting a plan creates one sales order with a line per treatment (linked to its phase);
  each treatment is invoiced as its visits are done (delivered quantity), never twice.
- "Treatment Board" menu: every open phase of every patient.
    """,
    'depends': ['dental_core', 'sale_project'],
    'data': [
        'security/dental_project_security.xml',
        'data/project_task_type_data.xml',
        'views/project_task_views.xml',
        'views/dental_treatment_plan_views.xml',
        'views/dental_case_views.xml',
        'views/dental_project_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dental_project/static/src/scss/dental_board.scss',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': True,
    'license': 'LGPL-3',
}
