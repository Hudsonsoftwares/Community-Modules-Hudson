import base64
import os

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from odoo.tests import BaseCase, tagged

from odoo.addons.abdm_base.tools import fidelius as f

# Start of every X.509 key produced by ABDM's Fidelius (BouncyCastle, explicit
# Curve25519 parameters), e.g. in the keyValue of ABDM sample requests.
ABDM_KEY_PREFIX = 'MIIBMTCB6gYHKoZIzj0CATCB3gIBATArBgcqhkjOPQEBAiB/'


@tagged('post_install', '-at_install', 'abdm')
class TestFidelius(BaseCase):

    def test_curve_parameters(self):
        self.assertTrue(f.is_on_curve((f.GX, f.GY)))
        self.assertIsNone(f.scalar_mult(f.N, (f.GX, f.GY)), 'n*G must be the point at infinity')

    def test_key_format_matches_abdm(self):
        key = f.KeyMaterial()
        self.assertTrue(key.public_key.startswith(ABDM_KEY_PREFIX))
        self.assertEqual(f.decode_public_key(key.public_key), key.public_point)
        material = key.to_abdm()
        self.assertEqual(material['cryptoAlg'], 'ECDH')
        self.assertEqual(material['curve'], 'Curve25519')
        self.assertEqual(len(base64.b64decode(material['nonce'])), 32)
        self.assertTrue(material['dhPublicKey']['expiry'].endswith('Z'))

    def test_same_group_as_x25519(self):
        """Weierstrass x = Montgomery u + A/3: compare with the X25519 implementation."""
        third = f.MONTGOMERY_A * pow(3, f.P - 2, f.P) % f.P
        for _ in range(3):
            raw = bytearray(os.urandom(32))
            raw[0] &= 248
            raw[31] = (raw[31] & 127) | 64
            private = X25519PrivateKey.from_private_bytes(bytes(raw))
            scalar = int.from_bytes(raw, 'little')
            public = f.scalar_mult(scalar, (f.GX, f.GY))
            self.assertEqual(((public[0] - third) % f.P).to_bytes(32, 'little'),
                             private.public_key().public_bytes_raw())
            other = X25519PrivateKey.generate()
            other_w = f._decompress(2, (int.from_bytes(other.public_key().public_bytes_raw(), 'little')
                                        + third) % f.P)
            shared = f.scalar_mult(scalar, other_w)
            self.assertEqual(((shared[0] - third) % f.P).to_bytes(32, 'little'),
                             private.exchange(other.public_key()))

    def test_encrypt_decrypt(self):
        hip, hiu = f.KeyMaterial(), f.KeyMaterial()
        message = '{"resourceType": "Bundle", "note": "ü 🦷"}'
        cipher = f.encrypt(message, hip, hiu.public_key, hiu.nonce_b64)
        self.assertNotIn('Bundle', cipher)
        self.assertEqual(f.decrypt(cipher, hiu, hip.public_key, hip.nonce_b64), message)
        with self.assertRaises(f.FideliusError):
            f.decrypt(cipher, f.KeyMaterial(), hip.public_key, hip.nonce_b64)
        restored = f.KeyMaterial.from_private(hiu.private_key_b64, hiu.nonce_b64)
        self.assertEqual(f.decrypt(cipher, restored, hip.public_key, hip.nonce_b64), message)

    def test_other_key_encodings(self):
        key = f.KeyMaterial()
        x, y = key.public_point
        raw = base64.b64encode(f.encode_point(key.public_point)).decode()
        compressed = base64.b64encode(bytes([2 + (y & 1)]) + x.to_bytes(32, 'big')).decode()
        self.assertEqual(f.decode_public_key(raw), key.public_point)
        self.assertEqual(f.decode_public_key(compressed), key.public_point)
        with self.assertRaises(f.FideliusError):
            f.decode_public_key(base64.b64encode(b'\x04' + b'\x01' * 64).decode())
