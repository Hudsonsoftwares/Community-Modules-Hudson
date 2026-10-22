{
    'name': 'Hudson Attendance Enhancement',
    'version': '1.0',
    'category': 'Human Resources/Attendance',
    'summary': 'Photo check-in/out, Radius Punching & Work From Home Live Tracking',
    'description': """
Hudson Attendance Enhancement
=============================
- Require photo when checking in and checking out.
- Enforce check-in/out within a configured radius of specified locations.
- Interactive map & search for configuring attendance locations.
- Work From Home (WFH) flexible scheduling and authorization.
- Real-time periodic GPS tracking for remote employees.
- Live interactive Admin Map showing remote employees, distance from home, and distance from check-in.
    """,
    'depends': ['hr_attendance', 'web'],
    'data': [
        'security/ir.access.csv',
        'views/hr_attendance_location_views.xml',
        'views/res_config_settings_views.xml',
        'views/hr_attendance_views.xml',
        'views/wfh_live_map_views.xml',
        'views/hr_attendance_gantt_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hudson_attendance_enhancement/static/lib/leaflet/leaflet.css',
            'hudson_attendance_enhancement/static/lib/leaflet/leaflet.js',
            'hudson_attendance_enhancement/static/src/css/location_map_widget.css',
            'hudson_attendance_enhancement/static/src/css/wfh_live_map.css',
            'hudson_attendance_enhancement/static/src/css/attendance_gantt.css',
            'hudson_attendance_enhancement/static/src/xml/camera_dialog.xml',
            'hudson_attendance_enhancement/static/src/xml/location_map_widget.xml',
            'hudson_attendance_enhancement/static/src/xml/wfh_live_map.xml',
            'hudson_attendance_enhancement/static/src/xml/employee_home_map_picker.xml',
            'hudson_attendance_enhancement/static/src/xml/attendance_gantt.xml',
            'hudson_attendance_enhancement/static/src/js/camera_dialog.js',
            'hudson_attendance_enhancement/static/src/js/attendance_menu_patch.js',
            'hudson_attendance_enhancement/static/src/js/location_map_widget.js',
            'hudson_attendance_enhancement/static/src/js/employee_home_map_picker.js',
            'hudson_attendance_enhancement/static/src/js/wfh_tracking_service.js',
            'hudson_attendance_enhancement/static/src/js/wfh_live_map.js',
            'hudson_attendance_enhancement/static/src/js/attendance_gantt_arch_parser.js',
            'hudson_attendance_enhancement/static/src/js/attendance_gantt_model.js',
            'hudson_attendance_enhancement/static/src/js/attendance_gantt_renderer.js',
            'hudson_attendance_enhancement/static/src/js/attendance_gantt_controller.js',
            'hudson_attendance_enhancement/static/src/js/attendance_gantt_view.js',
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
