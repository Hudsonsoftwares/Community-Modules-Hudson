{
    'name': 'Hudson Activity Monitor',
    'version': '20.0.1.1.0',
    'category': 'Human Resources',
    'summary': 'Employee computer activity: active/idle time and applications used, '
               'collected by the Hudson Activity desktop agent',
    'description': """
Hudson Activity Monitor
=======================
Receives activity data from the Hudson Activity desktop agent (Windows / macOS):

- Device pairing with one-time codes and per-device tokens (only a hash is stored).
- Active, idle and locked time; applications and (optionally) window titles.
- Timeline, daily summary, pivot/graph reports, live device status.
- Application categories (productive / neutral / unproductive) and productivity %.
- Comparison with attendance hours.
- Access: employees see their own data, managers their team, administrators everything.
  Window titles are visible to administrators only.
- Retention: raw activity is purged after a configurable number of days.
    """,
    'author': 'Hudson Softwares',
    'depends': ['hr', 'hr_attendance'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'data/ir_cron_data.xml',
        'views/hr_activity_span_views.xml',
        'views/hr_activity_daily_views.xml',
        'views/hr_activity_device_views.xml',
        'views/hr_activity_app_views.xml',
        'views/hr_employee_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hudson_activity_monitor/static/src/activity_gantt/activity_gantt.css',
            'hudson_activity_monitor/static/src/activity_gantt/activity_gantt.xml',
            'hudson_activity_monitor/static/src/activity_gantt/activity_gantt_model.js',
            'hudson_activity_monitor/static/src/activity_gantt/activity_gantt_controller.js',
            'hudson_activity_monitor/static/src/activity_gantt/activity_gantt_view.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
