# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
{
    'name': 'Face Kiosk Attendance',
    'summary': 'Browser based face match clock in and clock out for Odoo 20 Community, where face-api.js generates a 128 dimension embedding on the device and the server runs a cosine match against enrolled templates before posting to hr.attendance, with face recognition attendance, biometric clock in, kiosk time clock, contactless attendance, no badge attendance, buddy punch reduction, multi sample enrolment, per site geofence, consent linked templates, and an append only kiosk audit trail.',
    'description': 'Self hosted face match attendance kiosk for Odoo 20 Community. The browser captures a face and generates a 128 dimension embedding with face-api.js, sends only that embedding to the server, and the server cosine matches against active enrolled templates for the device company, then creates or closes an hr.attendance row. Raw images never leave the device. This is an attendance convenience face match, not an anti spoofing security control.',
    'author': 'ERP Heritage',
    'website': 'https://www.erpheritage.com.au/',
    'license': 'LGPL-3',
    'category': 'Human Resources/Attendances',
    'version': '20.0.1.2.0',
    'depends': ['eh_hr_attendance_base', 'eh_hr_core', 'hr_attendance'],
    'data': [
        'views/eh_hr_face_template_views.xml',
        'views/hr_employee_views.xml',
        'views/face_enrolment_wizard_views.xml',
        'views/kiosk_shell_template.xml',
        'views/menus.xml',
        'security/ir.access.csv',
    ],
    'assets': {
        'web.assets_backend': ['eh_hr_face_kiosk/static/src/js/enrolment_widget.js', 'eh_hr_face_kiosk/static/src/xml/enrolment_widget.xml'],
    },
    'images': ['static/description/banner.gif'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
