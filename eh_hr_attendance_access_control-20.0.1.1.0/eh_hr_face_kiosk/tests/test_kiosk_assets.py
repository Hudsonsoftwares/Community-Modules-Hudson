# -*- encoding: utf-8 -*-
"""Tests for the face-api.js vendoring check and the kiosk shell's
CDN fallback / setup-required behaviour.

A source checkout never contains the vendored face-api bundle (the
files are gitignored and operator-installed), so the HTTP tests below
exercise the not-vendored paths: CDN fallback by default, and the
setup-required panel when the fallback is disabled by policy.
"""
import os
import tempfile

from odoo.tests import HttpCase, TransactionCase, tagged

from ..controllers import kiosk_shell
from ..controllers.kiosk_shell import (
    _FACEAPI_CDN_LIB,
    _FACEAPI_LOCAL_LIB,
    _FACEAPI_MODEL_FILES,
    _faceapi_vendored,
)

# The shell controller tells the operator, at WARNING when it falls back to
# the CDN and at ERROR when the fallback is off and the kiosk cannot run.
# Both are deliberate, so the tests below assert them instead of letting
# them leak into the run as unexplained log lines.
SHELL_LOGGER = kiosk_shell.__name__


class TestFaceapiVendoredCheck(TransactionCase):

    def _make_bundle(self, root, skip=None, empty=None):
        skip = skip or set()
        empty = empty or set()
        lib_dir = os.path.join(root, 'static', 'lib', 'face-api')
        models_dir = os.path.join(lib_dir, 'models')
        os.makedirs(models_dir)
        for name, path in [('face-api.min.js', lib_dir)] + [
                (n, models_dir) for n in _FACEAPI_MODEL_FILES]:
            if name in skip:
                continue
            with open(os.path.join(path, name), 'w') as fh:
                if name not in empty:
                    fh.write('x')

    def test_complete_bundle_is_vendored(self):
        with tempfile.TemporaryDirectory() as root:
            self._make_bundle(root)
            self.assertTrue(_faceapi_vendored(root))

    def test_missing_shard_is_not_vendored(self):
        with tempfile.TemporaryDirectory() as root:
            self._make_bundle(root, skip={'face_recognition_model-shard2'})
            self.assertFalse(_faceapi_vendored(root))

    def test_empty_manifest_is_not_vendored(self):
        # A zero-byte file (interrupted download) must not count.
        with tempfile.TemporaryDirectory() as root:
            self._make_bundle(
                root, empty={'tiny_face_detector_model-weights_manifest.json'})
            self.assertFalse(_faceapi_vendored(root))

    def test_missing_library_is_not_vendored(self):
        with tempfile.TemporaryDirectory() as root:
            self._make_bundle(root, skip={'face-api.min.js'})
            self.assertFalse(_faceapi_vendored(root))

    def test_empty_root_is_not_vendored(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertFalse(_faceapi_vendored(root))


@tagged('post_install', '-at_install')
class TestKioskShellFallback(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.site = cls.env['eh.hr.kiosk.site'].create({
            'name': 'Assets HTTP Site',
            'code': 'assets-http',
            'company_id': cls.env.company.id,
        })

    def _page(self, level):
        """Open the kiosk page and assert the operator notice it must log."""
        with self.assertLogs(SHELL_LOGGER, level) as captured:
            resp = self.url_open('/eh_hr/kiosk/assets-http')
        self.assertEqual(resp.status_code, 200)
        return resp.text, '\n'.join(captured.output)

    def test_unvendored_page_uses_cdn_fallback(self):
        if _faceapi_vendored():
            self.skipTest('face-api bundle is vendored on this checkout')
        self.env['ir.config_parameter'].sudo().set_bool(
            'eh_hr_face_kiosk.disable_cdn_fallback', False)
        page, logged = self._page('WARNING')
        self.assertIn('fetch_face_api.sh', logged)
        self.assertIn(_FACEAPI_CDN_LIB, page)
        self.assertIn('data-faceapi-vendored="false"', page)
        self.assertIn('data-faceapi-blocked="false"', page)
        self.assertNotIn('Kiosk setup required', page)

    def test_unvendored_with_fallback_disabled_shows_setup_panel(self):
        if _faceapi_vendored():
            self.skipTest('face-api bundle is vendored on this checkout')
        self.env['ir.config_parameter'].sudo().set_bool(
            'eh_hr_face_kiosk.disable_cdn_fallback', True)
        try:
            page, logged = self._page('ERROR')
            self.assertIn('fetch_face_api.sh', logged)
            self.assertIn('Kiosk setup required', page)
            self.assertIn('fetch_face_api.sh', page)
            self.assertIn('data-faceapi-blocked="true"', page)
            self.assertIn(_FACEAPI_LOCAL_LIB, page)
            self.assertNotIn('cdn.jsdelivr.net', page)
        finally:
            self.env['ir.config_parameter'].sudo().set_bool(
                'eh_hr_face_kiosk.disable_cdn_fallback', False)
