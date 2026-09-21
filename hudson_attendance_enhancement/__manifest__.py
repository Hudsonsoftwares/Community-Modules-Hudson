{
    'name': 'Hudson Attendance Enhancement',
    'version': '1.0',
    'category': 'Human Resources/Attendance',
    'summary': 'Add Photo check-in/out and Radius Punching',
    'description': """
Hudson Attendance Enhancement
=============================
- Require photo when checking in and checking out.
- Enforce check-in/out within a configured radius of specified locations.
- Interactive map & search for configuring attendance locations.
    """,
    'depends': ['hr_attendance', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_attendance_location_views.xml',
        'views/res_config_settings_views.xml',
        'views/hr_attendance_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hudson_attendance_enhancement/static/lib/leaflet/leaflet.css',
            'hudson_attendance_enhancement/static/lib/leaflet/leaflet.js',
            'hudson_attendance_enhancement/static/src/css/location_map_widget.css',
            'hudson_attendance_enhancement/static/src/xml/camera_dialog.xml',
            'hudson_attendance_enhancement/static/src/xml/location_map_widget.xml',
            'hudson_attendance_enhancement/static/src/js/camera_dialog.js',
            'hudson_attendance_enhancement/static/src/js/attendance_menu_patch.js',
            'hudson_attendance_enhancement/static/src/js/location_map_widget.js',
        ],
        'hr_attendance.assets_public_attendance': [
            'hudson_attendance_enhancement/static/src/xml/camera_dialog.xml',
            'hudson_attendance_enhancement/static/src/js/camera_dialog.js',
            'hudson_attendance_enhancement/static/src/js/kiosk_patch.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
