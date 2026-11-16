{
    'name': 'ABDM - NHCX Insurance (National Health Claims Exchange)',
    'version': '20.0.1.0.0',
    'category': 'Healthcare',
    'summary': "Check patients' insurance eligibility and benefits with Indian insurers and "
               'TPAs through NHCX',
    'description': """
NHCX connector
==============
Connects ``insurance_base`` to India's National Health Claims Exchange (HCX
protocol, NRCeS FHIR R4 profiles). Specialty-independent: dental, eye,
physiotherapy... clinics use it the same way.

* Settings > ABDM > NHCX: API URL, login (reuses the ABDM client by default),
  participant code, endpoint URL to register, RSA key pair and the certificate
  to upload at onboarding
* Payers: sync insurers and TPAs (codes, encryption certificates) from the
  NHCX participant registry; connector "NHCX" on the insurance company
* Eligibility: "Check Eligibility" on a policy builds a CoverageEligibilityRequest
  (patient with ABHA, facility with HFR ID, coverage from the card), encrypts it
  (JWE RSA-OAEP-256 / A256GCM) for the payer and sends it; the payer's
  CoverageEligibilityResponse arrives on /nhcx/coverageeligibility/on_check and
  fills the check: in force, benefit period, benefits with allowed / used /
  remaining amounts, pre-authorization flags
* Every exchange is an ABDM transaction with its API log (payloads encrypted
  on the wire, readable in the transaction); unanswered requests time out

Pre-authorization and claims use the same transport and follow in a later version.
    """,
    'author': 'Hudson Software Solutions',
    'depends': ['abdm_abha', 'insurance_base'],
    'external_dependencies': {'python': ['requests', 'cryptography']},
    'data': [
        'views/res_config_settings_views.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
