{
    'name': 'Dental ABDM',
    'version': '20.0.1.2.0',
    'category': 'Dental Clinic',
    'summary': 'ABDM for the dental clinic: ABHA on the patient file and at reception',
    'description': """
Dental ABDM
===========
Milestone 1 (ABHA):

* "Create / Verify ABHA" on the dental patient form, ABHA number under the Patient ID
* Reception menu "ABHA Registration": verify or create an ABHA and register the
  patient in one go (date of birth and gender filled from ABHA KYC data)
* Reception, assistant, dentist and manager roles can use ABHA features

Milestone 2 (records): each dental case is turned into ABDM FHIR records
(OP consultation per signed-off examination, prescription per issued
prescription). Case form > Actions > "ABDM: Preview Health Records".

Milestone 2 (HIP): every dental case is a care context. Case > Actions >
"ABDM: Link Case to ABHA" links it; patients can also discover and link it from
the ABHA app, and consented requests receive the encrypted records.
    """,
    'author': 'Hudson Software Solutions',
    'depends': ['abdm_abha', 'abdm_hip', 'dental_patient', 'dental_appointment', 'dental_core', 'dental_pharmacy'],
    'data': [
        'data/dental_abdm_security.xml',
        'security/ir.access.csv',
        'views/abdm_fhir_preview_views.xml',
        'views/res_partner_views.xml',
        'views/dental_abdm_menus.xml',
        'views/dental_case_views.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
