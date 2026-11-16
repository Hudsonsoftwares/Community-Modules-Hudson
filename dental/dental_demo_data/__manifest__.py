{
    'name': 'Dental Demo Data',
    'version': '20.0.1.0.0',
    'category': 'Healthcare/Dental',
    'summary': 'Realistic demo clinic: staff, patients, appointments, cases, plans, invoices, lab, pharmacy, ortho, second opinions',
    'description': """
Loads a complete demo dental clinic on install (dates are relative to the install day):

* Doctors, receptionist, lab technician, pharmacist and assistants (with logins)
* The Administrator becomes a Dentist, so the Dentist Workspace shows his own day
* 45 patients with medical/dental history and allergies
* ~6 weeks of completed visits (cases, examinations, tooth findings, diagnoses,
  treatment plans, sessions, posted invoices and payments), today's live queue
  and three weeks of upcoming bookings
* Follow-ups, recalls, waiting list, CRM enquiries, clinic equipment and maintenance
* Prescriptions and pharmacy dispensing (with medicine batches in stock)
* Lab orders in every stage, orthodontic charts with visits, second opinions

Use Dental > Configuration > Refresh Today's Demo Schedule on later days to
book a fresh live queue for "today".

Install it only on a demo / test database.
""",
    'author': 'Hudson Softwares',
    'depends': [
        'dental_core',
        'dental_lab',
        'dental_pharmacy',
        'dental_orthodontics',
        'dental_second_opinion',
    ],
    'data': [
        'data/demo_actions.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
