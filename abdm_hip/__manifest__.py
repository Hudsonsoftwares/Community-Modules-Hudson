{
    'name': 'ABDM - Health Information Provider (HIP)',
    'version': '20.0.1.0.0',
    'category': 'Healthcare',
    'summary': 'Share health records through ABDM: care contexts, linking, '
               'consents and encrypted data transfer',
    'description': """
ABDM HIP (Milestone 2)
======================
Generic HIP engine; specialty modules decide what a care context is and which
FHIR records it holds (see ``abdm.care.context.mixin``).

* Care contexts (one per episode, e.g. a dental case) with link status
* HIP-initiated linking: link token + link care context
* Patient-initiated linking from the ABHA/PHR app: discovery, OTP, confirmation
* Consent notifications (granted / revoked / expired) stored as consent artefacts
* Health-information requests: records built, encrypted (Fidelius) and pushed
  to the requester, then the transfer status is notified to ABDM
* New-data notification for linked care contexts
    """,
    'author': 'Hudson Software Solutions',
    'depends': ['abdm_abha', 'sms'],
    'data': [
        'security/ir.access.csv',
        'views/abdm_hip_views.xml',
        'views/abdm_hip_menus.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
