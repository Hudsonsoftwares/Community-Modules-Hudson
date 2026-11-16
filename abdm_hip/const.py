"""ABDM V3 HIP endpoints (gateway paths, relative to the gateway URL).

Checked against the sandbox on 2026-11-12: each answers 401 without a token,
unknown paths answer 404.
"""
# HIP-initiated linking
PATH_GENERATE_LINK_TOKEN = '/v3/token/generate-token'
PATH_LINK_CARE_CONTEXT = '/hip/v3/link/carecontext'
PATH_CONTEXT_NOTIFY = '/hip/v3/link/context/notify'
# Patient-initiated linking (answers to discovery / init / confirm)
PATH_ON_DISCOVER = '/user-initiated-linking/v3/patient/care-context/on-discover'
PATH_ON_INIT = '/user-initiated-linking/v3/link/care-context/on-init'
PATH_ON_CONFIRM = '/user-initiated-linking/v3/link/care-context/on-confirm'
# Consent and data flow
PATH_CONSENT_ON_NOTIFY = '/consent/v3/request/hip/on-notify'
PATH_HI_ON_REQUEST = '/data-flow/v3/health-information/hip/on-request'
PATH_HI_NOTIFY = '/data-flow/v3/health-information/notify'

# Callback paths ABDM calls on our bridge URL (matched on their ending)
CB_ON_GENERATE_TOKEN = 'token/on-generate-token'
CB_ON_LINK_CARE_CONTEXT = ('link/on_carecontext', 'link/on-carecontext')
CB_DISCOVER = 'patient/care-context/discover'
CB_LINK_INIT = 'link/care-context/init'
CB_LINK_CONFIRM = 'link/care-context/confirm'
CB_CONSENT_NOTIFY = 'consent/request/hip/notify'
CB_HI_REQUEST = 'health-information/request'

OTP_VALIDITY_MINUTES = 10
LINK_TOKEN_VALIDITY_DAYS = 180
