"""ABDM health-information encryption ("Fidelius" scheme), pure Python.

ABDM requires every health record sent between HIP and HIU to be encrypted:

* ECDH key agreement on Curve25519 in *Weierstrass* form (BouncyCastle
  "curve25519"), keys exchanged as X.509 SubjectPublicKeyInfo with explicit
  curve parameters (what BouncyCastle/Fidelius produce);
* xor = senderNonce XOR requesterNonce (32 bytes each);
* AES key = HKDF-SHA256(ikm=shared secret, salt=xor[:20], info=none, 32 bytes);
* AES-256-GCM with IV = xor[-12:], 128-bit tag appended, base64 output.

``cryptography`` only offers X25519 (Montgomery form, different key format),
so the Weierstrass arithmetic is implemented here. It is checked in the tests
against X25519 (same group, x_weierstrass = u_montgomery + A/3).
"""
import base64
import os
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# --- Curve25519, Weierstrass form: y^2 = x^3 + a*x + b (mod p) -------------
P = 2 ** 255 - 19
A = 0x2AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA984914A144
B = 0x7B425ED097B425ED097B425ED097B425ED097B425ED097B4260B5E9C7710C864
GX = 0x2AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD245A
GY = 0x20AE19A1B8A086B4E01EDD2C7748D14C923D4D7E6D7C61B229E9C5A27ECED3D9
N = 0x1000000000000000000000000000000014DEF9DEA2F79CD65812631A5CF5D3ED
H = 8
MONTGOMERY_A = 486662  # x_weierstrass = u_montgomery + MONTGOMERY_A / 3

CRYPTO_ALG = 'ECDH'
CURVE = 'Curve25519'
KEY_PARAMETERS = 'Curve25519/32byte random key'


class FideliusError(ValueError):
    pass


# --- point arithmetic (Jacobian coordinates) --------------------------------
def _inv(x):
    return pow(x, P - 2, P)


def _to_jacobian(point):
    return (point[0], point[1], 1)


def _from_jacobian(jp):
    x, y, z = jp
    if z == 0:
        return None
    zi = _inv(z)
    zi2 = zi * zi % P
    return (x * zi2 % P, y * zi2 * zi % P)


def _double(jp):
    x, y, z = jp
    if y == 0 or z == 0:
        return (0, 0, 0)
    ysq = y * y % P
    s = 4 * x * ysq % P
    z2 = z * z % P
    m = (3 * x * x + A * z2 * z2) % P
    nx = (m * m - 2 * s) % P
    ny = (m * (s - nx) - 8 * ysq * ysq) % P
    nz = 2 * y * z % P
    return (nx, ny, nz)


def _add(p1, p2):
    if p1[2] == 0:
        return p2
    if p2[2] == 0:
        return p1
    x1, y1, z1 = p1
    x2, y2, z2 = p2
    z1s, z2s = z1 * z1 % P, z2 * z2 % P
    u1, u2 = x1 * z2s % P, x2 * z1s % P
    s1, s2 = y1 * z2s * z2 % P, y2 * z1s * z1 % P
    if u1 == u2:
        return _double(p1) if s1 == s2 else (0, 0, 0)
    h = (u2 - u1) % P
    r = (s2 - s1) % P
    h2 = h * h % P
    h3 = h * h2 % P
    u1h2 = u1 * h2 % P
    nx = (r * r - h3 - 2 * u1h2) % P
    ny = (r * (u1h2 - nx) - s1 * h3) % P
    nz = h * z1 * z2 % P
    return (nx, ny, nz)


def scalar_mult(k, point):
    result = (0, 0, 0)
    addend = _to_jacobian(point)
    while k:
        if k & 1:
            result = _add(result, addend)
        addend = _double(addend)
        k >>= 1
    return _from_jacobian(result)


def is_on_curve(point):
    x, y = point
    return (y * y - (x * x * x + A * x + B)) % P == 0


# --- encoding ---------------------------------------------------------------
def _der_len(n):
    if n < 0x80:
        return bytes([n])
    raw = n.to_bytes((n.bit_length() + 7) // 8, 'big')
    return bytes([0x80 | len(raw)]) + raw


def _der(tag, content):
    return bytes([tag]) + _der_len(len(content)) + content


def _der_int(value):
    raw = value.to_bytes((value.bit_length() + 8) // 8 or 1, 'big')  # keep sign bit clear
    return _der(0x02, raw)


def _int32(value):
    return value.to_bytes(32, 'big')


_OID_EC_PUBLIC_KEY = bytes.fromhex('06072a8648ce3d0201')   # 1.2.840.10045.2.1
_OID_PRIME_FIELD = bytes.fromhex('06072a8648ce3d0101')     # 1.2.840.10045.1.1
_EC_PARAMETERS = _der(0x30, b''.join([
    _der_int(1),
    _der(0x30, _OID_PRIME_FIELD + _der_int(P)),
    _der(0x30, _der(0x04, _int32(A)) + _der(0x04, _int32(B))),
    _der(0x04, b'\x04' + _int32(GX) + _int32(GY)),
    _der_int(N),
    _der_int(H),
]))


def encode_point(point):
    return b'\x04' + _int32(point[0]) + _int32(point[1])


def public_key_to_x509(point):
    """X.509 SubjectPublicKeyInfo, explicit curve parameters, base64."""
    algorithm = _der(0x30, _OID_EC_PUBLIC_KEY + _EC_PARAMETERS)
    spki = _der(0x30, algorithm + _der(0x03, b'\x00' + encode_point(point)))
    return base64.b64encode(spki).decode()


def _read_tlv(data, pos):
    tag = data[pos]
    length = data[pos + 1]
    pos += 2
    if length & 0x80:
        count = length & 0x7F
        length = int.from_bytes(data[pos:pos + count], 'big')
        pos += count
    return tag, data[pos:pos + length], pos + length


def _decompress(prefix, x):
    y2 = (x * x * x + A * x + B) % P
    # p = 5 mod 8: Atkin's square root
    y = pow(y2, (P + 3) // 8, P)
    if (y * y - y2) % P:
        y = y * pow(2, (P - 1) // 4, P) % P
    if (y * y - y2) % P:
        raise FideliusError('point not on curve')
    if (y & 1) != (prefix & 1):
        y = P - y
    return (x, y)


def decode_public_key(value):
    """Accept X.509 SPKI (explicit or named curve), or a raw 65/33-byte point, base64."""
    try:
        data = base64.b64decode(value.strip())
    except (ValueError, AttributeError) as exc:
        raise FideliusError('public key is not base64') from exc
    if data[:1] == b'\x30':
        tag, seq, _ = _read_tlv(data, 0)
        _, _, pos = _read_tlv(seq, 0)          # AlgorithmIdentifier
        tag, bits, _ = _read_tlv(seq, pos)     # subjectPublicKey
        if tag != 0x03:
            raise FideliusError('unexpected public key structure')
        data = bits[1:]                        # skip "unused bits" byte
    if len(data) == 65 and data[0] == 4:
        point = (int.from_bytes(data[1:33], 'big'), int.from_bytes(data[33:], 'big'))
    elif len(data) == 33 and data[0] in (2, 3):
        point = _decompress(data[0], int.from_bytes(data[1:], 'big'))
    else:
        raise FideliusError('unsupported public key encoding')
    if not is_on_curve(point):
        raise FideliusError('public key is not on Curve25519')
    return point


# --- key material -----------------------------------------------------------
class KeyMaterial:
    """One-time key pair + nonce for one data exchange."""

    def __init__(self, private_key=None, nonce=None):
        self.private_key = private_key or (int.from_bytes(os.urandom(32), 'big') % (N - 1)) + 1
        self.public_point = scalar_mult(self.private_key, (GX, GY))
        self.nonce = nonce or os.urandom(32)

    @property
    def public_key(self):
        return public_key_to_x509(self.public_point)

    @property
    def nonce_b64(self):
        return base64.b64encode(self.nonce).decode()

    @property
    def private_key_b64(self):
        return base64.b64encode(_int32(self.private_key)).decode()

    @classmethod
    def from_private(cls, private_key_b64, nonce_b64):
        return cls(int.from_bytes(base64.b64decode(private_key_b64), 'big'), base64.b64decode(nonce_b64))

    def to_abdm(self, expiry_hours=24):
        """The ``keyMaterial`` object of ABDM HI requests / transfers."""
        expiry = datetime.now(timezone.utc) + timedelta(hours=expiry_hours)
        return {
            'cryptoAlg': CRYPTO_ALG,
            'curve': CURVE,
            'dhPublicKey': {
                'expiry': expiry.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (expiry.microsecond // 1000),
                'parameters': KEY_PARAMETERS,
                'keyValue': self.public_key,
            },
            'nonce': self.nonce_b64,
        }


def _aes_params(private_key, peer_public_key, own_nonce, peer_nonce):
    peer = decode_public_key(peer_public_key)
    shared = scalar_mult(private_key, peer)
    if shared is None:
        raise FideliusError('invalid shared secret')
    own = own_nonce if isinstance(own_nonce, bytes) else base64.b64decode(own_nonce)
    other = peer_nonce if isinstance(peer_nonce, bytes) else base64.b64decode(peer_nonce)
    if len(own) != 32 or len(other) != 32:
        raise FideliusError('nonces must be 32 bytes')
    xor = bytes(x ^ y for x, y in zip(own, other))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=xor[:20], info=None).derive(_int32(shared[0]))
    return key, xor[-12:]


def encrypt(plain_text, own: KeyMaterial, peer_public_key, peer_nonce):
    key, iv = _aes_params(own.private_key, peer_public_key, own.nonce, peer_nonce)
    data = plain_text.encode() if isinstance(plain_text, str) else plain_text
    return base64.b64encode(AESGCM(key).encrypt(iv, data, None)).decode()


def decrypt(cipher_text, own: KeyMaterial, peer_public_key, peer_nonce):
    key, iv = _aes_params(own.private_key, peer_public_key, own.nonce, peer_nonce)
    try:
        return AESGCM(key).decrypt(iv, base64.b64decode(cipher_text), None).decode()
    except Exception as exc:  # InvalidTag, bad base64...
        raise FideliusError('could not decrypt health information') from exc
