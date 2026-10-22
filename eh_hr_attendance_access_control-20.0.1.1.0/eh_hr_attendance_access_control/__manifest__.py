# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
{
    'name': 'Door Access Control',
    'summary': "Door Access Control connects your attendance kiosk to physical doors: when an authorised employee passes a face match, the suite POSTs an unlock command to your reader's webhook and writes an audit row whether the door opened, was denied, or errored. Per-employee per-zone permissions, optional validity dates, bearer-token webhook auth, and a per-company isolated event log make it usable across sites. Keywords: Odoo 20 Community door access control, face access, biometric door unlock, attendance access control, hr_attendance door integration, kiosk face match unlock, Wiegand bridge, relay door unlock, webhook reader, zone permissions, access audit trail.",
    'description': "Adds physical access control to the ERP Heritage attendance kiosk. A successful face match at a kiosk fires an unlock call to the reader configured for that site's zone, subject to per-employee permissions, and records the outcome in an append-only event log. The reader protocol is a single HTTP webhook for hardware neutrality, so any relay, Wiegand, or proprietary board is driven through a small bridge service. Free, LGPL-3, source on disk.",
    'author': 'ERP Heritage',
    'website': 'https://www.erpheritage.com.au/',
    'license': 'LGPL-3',
    'category': 'Human Resources/Attendances',
    'version': '20.0.1.1.0',
    'depends': ['eh_hr_attendance_base', 'eh_hr_face_kiosk', 'eh_hr_core'],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'data/cron.xml',
        'views/eh_hr_access_zone_views.xml',
        'views/eh_hr_access_reader_views.xml',
        'views/eh_hr_access_permission_views.xml',
        'views/eh_hr_access_event_views.xml',
        'views/hr_employee_views.xml',
        'views/menus.xml',
        'views/kiosk_shell_inherit.xml',
        'security/ir.access.csv',
    ],
    'images': ['static/description/banner.gif'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
