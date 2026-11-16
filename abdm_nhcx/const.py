"""NHCX (National Health Claims Exchange) protocol constants.

NHCX implements the open HCX protocol: every request is a FHIR bundle,
encrypted (JWE) for the recipient, sent to the exchange, which forwards it to
the payer; the payer answers asynchronously on our ``on_*`` endpoint.

Paths and FHIR identifier systems follow the HCX protocol specification and
the NRCeS NHCX implementation guide. They could not be checked against the
NHCX sandbox when this module was written: confirm them with the NHCX
onboarding kit and adjust here (one-line edits), or in Settings for the URLs.
"""

# --- API actions, relative to the NHCX API URL --------------------------------
PATH_COVERAGE_ELIGIBILITY_CHECK = '/coverageeligibility/check'
PATH_PREAUTH_SUBMIT = '/preauth/submit'
PATH_CLAIM_SUBMIT = '/claim/submit'
PATH_COMMUNICATION_ON_REQUEST = '/communication/on_request'
PATH_STATUS = '/hcx/status'
PATH_PARTICIPANT_SEARCH = '/participant/search'

# Callback actions the exchange calls on our endpoint (<endpoint>/<action>)
CALLBACK_ACTIONS = {
    'coverageeligibility/on_check': 'coverage_eligibility',
    'preauth/on_submit': 'preauth',
    'claim/on_submit': 'claim',
    'communication/request': 'communication',
    'paymentnotice/request': 'payment_notice',
    'hcx/on_status': 'status',
}

# --- protocol headers (inside the JWE protected header) ----------------------
H_API_CALL_ID = 'x-hcx-api_call_id'
H_CORRELATION_ID = 'x-hcx-correlation_id'
H_WORKFLOW_ID = 'x-hcx-workflow_id'
H_SENDER = 'x-hcx-sender_code'
H_RECIPIENT = 'x-hcx-recipient_code'
H_TIMESTAMP = 'x-hcx-timestamp'
H_STATUS = 'x-hcx-status'
H_ERROR = 'x-hcx-error_details'

STATUS_REQUEST = 'request.initiated'
STATUS_COMPLETE = 'response.complete'
STATUS_PARTIAL = 'response.partial'
STATUS_ERROR = 'response.error'

# Participant roles in the registry
ROLE_PAYER = 'payor'
ROLE_TPA = 'agency.tpa'
ROLE_PROVIDER = 'provider'

# --- FHIR (NRCeS NHCX profiles) ---------------------------------------------
PROFILE = 'https://nrces.in/ndhm/fhir/r4/StructureDefinition/'
PARTICIPANT_SYSTEM = 'https://hcx.abdm.gov.in/participant'
POLICY_SYSTEM = 'https://hcx.abdm.gov.in/policy'
MEMBER_SYSTEM = 'https://hcx.abdm.gov.in/member'
REQUEST_SYSTEM = 'https://hcx.abdm.gov.in/request'
RELATIONSHIP_SYSTEM = 'http://terminology.hl7.org/CodeSystem/subscriber-relationship'

DEFAULT_TIMEOUT = 30
TOKEN_EXPIRY_MARGIN = 60
