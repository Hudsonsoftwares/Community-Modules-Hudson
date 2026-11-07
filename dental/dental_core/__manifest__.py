{
    'name': 'Dental Core',
    'version': '1.0.4',
    'category': 'Healthcare/Dental',
    'summary': 'Clinical consultation and treatment management for Dental Clinics',
    'author': 'Hudson Software Solutions',
    'description': """
Dental Core Module
==================
Builds the clinical consultation and treatment management foundation that starts after a patient checks in for an appointment.

Key Features:
- Dental Cases
- Clinical Examinations
- Diagnoses
- Treatment Plans
- Treatment Sessions
    """,
    'depends': [
        'base',
        'dental_base',
        'dental_patient',
        'dental_catalog',
        'dental_appointment',
        'hr',
        'mail',
        'account',
        'crm',
        'maintenance',
        'hr_maintenance',
    ],
    'data': [
        'security/dental_core_security.xml',
        'security/ir.access.csv',
        'data/dental_case_sequence.xml',
        'data/dental_tooth_finding_sequence.xml',
        'data/dental_treatment_plan_sequence.xml',
        'data/dental_equipment_data.xml',
        'views/crm_lead_views.xml',
        'views/dental_case_views.xml',
        'views/dental_tooth_finding_views.xml',
        'views/dental_clinical_examination_views.xml',
        'views/dental_diagnosis_views.xml',
        'views/dental_treatment_plan_views.xml',
        'views/dental_appointment_views_inherit.xml',
        'views/res_partner_views_inherit.xml',
        'views/dental_core_menus.xml',
        'views/dental_patient_document_views.xml',
        'views/dental_reporting_views.xml',
        'views/dental_dashboards.xml',
        'views/dental_maintenance_views.xml',
        'views/dental_maintenance_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dental_core/static/lib/three.min.js',
            'dental_core/static/lib/OrbitControls.js',
            'dental_core/static/lib/meshopt_decoder.js',
            'dental_core/static/lib/GLTFLoader.js',
            'dental_core/static/src/css/dentist_dashboard.scss',
            'dental_core/static/src/css/admin_dashboard.scss',
            'dental_core/static/src/js/admin_dashboard.js',
            'dental_core/static/src/xml/admin_dashboard.xml',
            'dental_core/static/src/js/dentist_dashboard.js',
            'dental_core/static/src/xml/dentist_dashboard.xml',
            'dental_core/static/src/css/receptionist_dashboard.scss',
            'dental_core/static/src/js/receptionist_dashboard.js',
            'dental_core/static/src/xml/receptionist_dashboard.xml',
            'dental_core/static/src/css/dental_odontogram_3d.scss',
            'dental_core/static/src/js/dental_odontogram_3d.js',
            'dental_core/static/src/xml/dental_odontogram_3d.xml',
            'dental_core/static/src/css/maintenance_dashboard.scss',
            'dental_core/static/src/js/maintenance_dashboard.js',
            'dental_core/static/src/xml/maintenance_dashboard.xml',
            'dental_core/static/src/css/waiting_queue_board.scss',
            'dental_core/static/src/js/waiting_queue_board.js',
            'dental_core/static/src/xml/waiting_queue_board.xml',
        ],
        'web.assets_backend_lazy': [
            'dental_core/static/src/js/graph_view_patch.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': ['dental_appointment'],
    'license': 'LGPL-3',
}
