"""Static ABDM (Ayushman Bharat Digital Mission) endpoints for the V3 APIs.

Every URL lives here so a change announced by NHA needs a one-line edit.
Paths were checked against the sandbox on 2026-11-11 (they answer 401 without
a token, unknown paths answer 404). Production base URLs can be overridden in
Settings > ABDM without touching code.
"""

ENVIRONMENTS = {
    'sandbox': {
        'gateway_url': 'https://dev.abdm.gov.in/api/hiecm',
        'abha_url': 'https://abhasbx.abdm.gov.in/abha/api',
        'cm_id': 'sbx',
    },
    'production': {
        'gateway_url': 'https://live.abdm.gov.in/api/hiecm',
        # Not verifiable before production approval: confirm with NHA and
        # set the override in Settings if it differs.
        'abha_url': 'https://abha.abdm.gov.in/abha/api',
        'cm_id': 'abdm',
    },
}

# Gateway (HIE-CM) paths, relative to gateway_url
PATH_SESSIONS = '/gateway/v3/sessions'
PATH_CERTS = '/gateway/v3/certs'
PATH_BRIDGE_URL = '/gateway/v3/bridge/url'
PATH_BRIDGE_SERVICES = '/gateway/v3/bridge-services'

# ABHA paths, relative to abha_url
PATH_ABHA_PUBLIC_CERT = '/v3/profile/public/certificate'

# Seconds removed from the token lifetime so we refresh before it expires.
TOKEN_EXPIRY_MARGIN = 60
DEFAULT_TIMEOUT = 30

# Body keys whose values must never be written to the API log.
SENSITIVE_KEYS = {
    'clientsecret', 'accesstoken', 'refreshtoken', 'otp', 'otpvalue',
    'aadhaar', 'aadhaarnumber', 'loginid', 'password', 'authorization',
    'x-token', 't-token', 'xtoken', 'ttoken', 'token',
    # photos are large and personal: never copy them into logs
    'photo', 'profilephoto', 'kycphoto',
}
