# -*- coding: utf-8 -*-
{
    'name': 'Dental Clinic Management - Online Video Consultation',
    'version': '20.0.1.0.0',
    'category': 'Healthcare/Dental',
    'summary': 'Online video consultations with patients on Odoo Discuss: secure join links, '
               'waiting room, pay-before-join, portal access and consent-gated recording',
    'description': """
Online Video Consultation (Teleconsultation)
============================================
Runs dental consultations over the native Odoo Discuss video call. No third-party video service.

* Any appointment can be booked as an **Online Video** consultation, by the front desk or by the
  patient on the website booking page (where the branch and appointment type allow it).
* On confirmation a private, PHI-flagged video room is created for the doctor, and the patient
  receives a secure join link by email.
* Patients join either with the **guest link** (identity check on date of birth or phone) or by
  **logging in to the patient portal** (My Online Consultations).
* **Pay before joining**: a consultation-fee invoice is posted at confirmation and the waiting
  room only opens once it is paid online (or the fee is waived by the clinic).
* **Waiting room** with camera/microphone test and telemedicine consent; the doctor is alerted
  and **admits** the patient into the call.
* Ending the consultation removes the patient from the room and saves the chat transcript on
  the appointment.
* **Recording is configurable** per branch and additionally requires the patient's consent
  (recording itself needs an Odoo SFU server); recordings are reachable from the appointment.
* **Electronic consent record** (PDF: wording accepted, time, identification method, IP address, browser).
* **Visit summary** PDF and email with the prescriptions; the summary stays on the patient's link.
* **Invite a colleague** (specialist, assistant, interpreter) into the call.
* Online / in-clinic choice in the **website booking** page and the **staff booking flow**.
* **Reports**: volumes, outcomes, waiting and call times, fees (Dental > Reports > Online Consultations).
    """,
    'author': 'Hudson Software Solutions',
    'license': 'LGPL-3',
    'depends': [
        'dental_discuss',
        'dental_core',
        'website',
        'portal',
        'account_payment',
        'dental_website_appointment',
        'dental_pharmacy',
    ],
    'data': [
        'security/ir.access.csv',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'data/portal_entry_data.xml',
        'views/dental_appointment_views.xml',
        'views/dental_appointment_type_views.xml',
        'views/res_config_settings_views.xml',
        'views/teleconsult_templates.xml',
        'views/portal_templates.xml',
        'views/website_booking_templates.xml',
        'views/teleconsult_invite_views.xml',
        'views/teleconsult_report_views.xml',
        'report/teleconsult_reports.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dental_teleconsult/static/src/booking_flow/*',
        ],
        'web.assets_frontend': [
            'dental_teleconsult/static/src/scss/teleconsult.scss',
            'dental_teleconsult/static/src/interactions/teleconsult_lobby.js',
            'dental_teleconsult/static/src/interactions/teleconsult_booking.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
