"""JWE (RFC 7516) for the HCX / NHCX protocol, compact serialization only.

NHCX payloads are encrypted for the recipient participant with
``alg = RSA-OAEP-256`` (the content key is wrapped with the recipient's RSA
public key, OAEP with SHA-256) and ``enc = A256GCM`` (AES-256-GCM, 96-bit IV,
128-bit tag). The protected header also carries the ``x-hcx-*`` protocol
headers, readable by the exchange for routing, while the FHIR payload is not.

Also generates the RSA key pair and the self-signed certificate a participant
uploads during NHCX onboarding.
"""
import base64
import json
import os
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import NameOID

ALG = 'RSA-OAEP-256'
ENC = 'A256GCM'


class JweError(ValueError):
    pass


def b64url_encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def b64url_decode(value):
    if isinstance(value, str):
        value = value.encode()
    value += b'=' * (-len(value) % 4)
    return base64.urlsafe_b64decode(value)


def _oaep():
    return padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


# --- keys -------------------------------------------------------------------
def load_public_key(pem):
    """Load an RSA public key from a PEM certificate or PEM public key (str/bytes)."""
    if not pem:
        raise JweError('no certificate / public key')
    data = pem.encode() if isinstance(pem, str) else pem
    data = data.strip()
    try:
        if b'BEGIN CERTIFICATE' in data:
            return x509.load_pem_x509_certificate(data).public_key()
        if b'BEGIN' in data:
            return serialization.load_pem_public_key(data)
        # bare base64 DER certificate
        return x509.load_der_x509_certificate(base64.b64decode(data)).public_key()
    except (ValueError, TypeError) as exc:
        raise JweError('invalid certificate / public key: %s' % exc) from exc


def load_private_key(pem):
    if not pem:
        raise JweError('no private key')
    data = pem.encode() if isinstance(pem, str) else pem
    try:
        return serialization.load_pem_private_key(data.strip(), password=None)
    except (ValueError, TypeError) as exc:
        raise JweError('invalid private key: %s' % exc) from exc


def generate_key_pair(common_name, organization=None, days=730, key_size=2048):
    """Return (private key PEM, self-signed certificate PEM) as str."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    attributes = [x509.NameAttribute(NameOID.COMMON_NAME, common_name[:64])]
    if organization:
        attributes.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization[:64]))
    attributes.append(x509.NameAttribute(NameOID.COUNTRY_NAME, 'IN'))
    name = x509.Name(attributes)
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return private_pem.decode(), cert.public_bytes(serialization.Encoding.PEM).decode()


def certificate_info(pem):
    """Subject and validity of a PEM certificate, for display."""
    cert = x509.load_pem_x509_certificate(pem.encode() if isinstance(pem, str) else pem)
    return {
        'subject': cert.subject.rfc4514_string(),
        'not_after': cert.not_valid_after_utc,
        'serial': format(cert.serial_number, 'x'),
    }


# --- JWE ----------------------------------------------------------------------
def encrypt(payload, protected_header, public_key):
    """Encrypt ``payload`` (dict or str) for ``public_key``. Returns the compact JWE."""
    header = dict(protected_header, alg=ALG, enc=ENC)
    header_b64 = b64url_encode(json.dumps(header, separators=(',', ':')).encode())
    plaintext = payload if isinstance(payload, (bytes, str)) else json.dumps(payload, separators=(',', ':'))
    if isinstance(plaintext, str):
        plaintext = plaintext.encode()
    cek = AESGCM.generate_key(bit_length=256)
    iv = os.urandom(12)
    encrypted_key = public_key.encrypt(cek, _oaep())
    sealed = AESGCM(cek).encrypt(iv, plaintext, header_b64.encode('ascii'))
    ciphertext, tag = sealed[:-16], sealed[-16:]
    return '.'.join([header_b64, b64url_encode(encrypted_key), b64url_encode(iv),
                     b64url_encode(ciphertext), b64url_encode(tag)])


def read_header(token):
    """Protected header of a compact JWE, without decrypting it."""
    try:
        header_b64 = token.split('.', 1)[0]
        return json.loads(b64url_decode(header_b64))
    except (ValueError, AttributeError, IndexError) as exc:
        raise JweError('malformed JWE header') from exc


def decrypt(token, private_key):
    """Decrypt a compact JWE. Returns (protected header dict, payload)."""
    try:
        header_b64, ek_b64, iv_b64, ct_b64, tag_b64 = token.strip().split('.')
    except (ValueError, AttributeError) as exc:
        raise JweError('malformed JWE (expected 5 parts)') from exc
    header = read_header(token)
    if header.get('alg') != ALG or header.get('enc') != ENC:
        raise JweError('unsupported JWE algorithm %s/%s' % (header.get('alg'), header.get('enc')))
    try:
        cek = private_key.decrypt(b64url_decode(ek_b64), _oaep())
        plaintext = AESGCM(cek).decrypt(
            b64url_decode(iv_b64), b64url_decode(ct_b64) + b64url_decode(tag_b64),
            header_b64.encode('ascii'))
    except Exception as exc:  # noqa: BLE001 - InvalidTag, ValueError...
        raise JweError('cannot decrypt: wrong key or tampered payload') from exc
    try:
        payload = json.loads(plaintext)
    except ValueError:
        payload = plaintext.decode('utf-8', errors='replace')
    return header, payload
