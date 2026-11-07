# -*- coding: utf-8 -*-
{
    'name': 'Dental Website Appointment Booking',
    'version': '1.0',
    'category': 'Website/Healthcare',
    'summary': 'Online Website Appointment Booking for Dental Clinics',
    'description': """
Dental Website Appointment Booking
==================================
Enables patients to book appointments online through the clinic website.
Preserves the 6-step modern animated booking workflow, dentist selection,
service selection, real-time availability checking, and instant booking confirmation.
Builds directly on the standalone dental_appointment module.
    """,
    'author': 'Hudson Software Solutions',
    'depends': [
        'dental_appointment',
        'website',
    ],
    'data': [
        'views/website_appointment_templates.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': ['dental_appointment', 'website'],
    'license': 'LGPL-3',
}
