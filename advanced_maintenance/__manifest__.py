{
    'name': 'Advanced Maintenance',
    'version': '1.0',
    'summary': 'Advanced Maintenance with Transfer and Location details',
    'description': 'Adds previous employee, transfer date, and location to maintenance equipment.',
    'category': 'Maintenance',
    'depends': ['maintenance', 'hr_maintenance'],
    'data': [
        'views/maintenance_equipment_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
