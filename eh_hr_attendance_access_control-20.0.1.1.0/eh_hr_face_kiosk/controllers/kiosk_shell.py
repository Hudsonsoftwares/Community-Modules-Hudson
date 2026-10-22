# -*- encoding: utf-8 -*-
"""Kiosk shell HTML route.

Renders the public kiosk page at /eh_hr/kiosk/<site_code>. The page
loads face-api.js from static/lib/face-api/, the suite's kiosk
JavaScript from static/src/js/, and the kiosk SCSS bundle. Browser
captures + matches happen client-side; the only server endpoints the
shell calls after pair are heartbeat, whoami, and face/match.

The kiosk does not require an Odoo login. Pairing is the auth boundary:
the device gets a token at pair time, and every subsequent request
carries that token in the X-EH-Kiosk-Token header.

Asset versioning
----------------

The kiosk shell loads its JS / CSS via direct <script> and <link>
tags (not via the asset bundle pipeline, because the kiosk is a
public standalone page). Browsers cache those files aggressively. To
make sure clients pick up new builds without a full cache wipe, we
compute the max mtime of the kiosk-side static assets at request
time and append it as a `?v=<int>` query string to each tag. The
URL is stable while the files are unchanged so the cache still
works for unchanged deploys.

face-api.js delivery
--------------------

The face-api.js library and its model weights are deliberately not
vendored in the module (see static/lib/face-api/README.md). At
request time this controller checks whether the operator has placed
the files locally:

* All present -> the page serves them from this Odoo instance.
* Any missing -> the page falls back to a pinned, immutable CDN
  build so the kiosk still works out of the box, and a warning is
  logged telling the operator how to vendor the files
  (tools/fetch_face_api.sh).

The fallback can be disabled for air-gapped or no-third-party
deployments with the ir.config_parameter
``eh_hr_face_kiosk.disable_cdn_fallback`` set to a boolean true value
(1, true, t, y, yes or on); the kiosk page then shows a
setup-required message instead of calling out to the CDN.
"""
import os

from odoo import http
from odoo.http import request

import logging

_logger = logging.getLogger(__name__)


# Files contributing to the kiosk-side asset version stamp. We scan
# both the core kiosk module and every extension that hooks into
# kiosk_shell_inherit, so the browser refetches whenever any of
# them changes. Missing files are tolerated (the extension may not
# be installed).
_KIOSK_ASSET_FILES = (
    # core
    ('eh_hr_face_kiosk', 'static/src/js/kiosk_shell.js'),
    ('eh_hr_face_kiosk', 'static/src/js/face_capture.js'),
    ('eh_hr_face_kiosk', 'static/src/scss/kiosk.css'),
    # extensions
    ('eh_hr_attendance_jobcost', 'static/src/js/job_picker.js'),
    ('eh_hr_attendance_jobcost', 'static/src/scss/job_picker.css'),
    ('eh_hr_attendance_access_control', 'static/src/js/access_trigger.js'),
    ('eh_hr_health_screen', 'static/src/js/health_screen.js'),
    ('eh_hr_health_screen', 'static/src/scss/health_screen.css'),
    ('eh_hr_face_liveness', 'static/src/js/liveness.js'),
    ('eh_hr_face_liveness', 'static/src/scss/liveness.css'),
)


def _kiosk_asset_version():
    """Return an int that bumps whenever any kiosk asset file mtime changes."""
    addons_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    latest = 0
    for module, rel in _KIOSK_ASSET_FILES:
        path = os.path.join(addons_root, module, rel)
        try:
            mt = int(os.path.getmtime(path))
            if mt > latest:
                latest = mt
        except OSError:
            continue
    return latest or 1


# The face-api.js bundle the operator vendors at deploy time. All of
# these must exist (and be non-empty) for the kiosk to serve the
# library locally; otherwise the page falls back to the pinned CDN
# build below.
_FACEAPI_LIB_REL = 'static/lib/face-api/face-api.min.js'
_FACEAPI_MODEL_FILES = (
    'tiny_face_detector_model-weights_manifest.json',
    'tiny_face_detector_model-shard1',
    'face_landmark_68_model-weights_manifest.json',
    'face_landmark_68_model-shard1',
    'face_recognition_model-weights_manifest.json',
    'face_recognition_model-shard1',
    'face_recognition_model-shard2',
)

# Pinned, immutable CDN build used as the fallback. The tag pin means
# the served bytes can never change underneath a deployment; jsDelivr
# serves tagged GitHub content with permanent caching.
_FACEAPI_CDN_LIB = 'https://cdn.jsdelivr.net/gh/justadudewhohacks/face-api.js@0.22.2/dist/face-api.min.js'
_FACEAPI_CDN_MODELS = 'https://cdn.jsdelivr.net/gh/justadudewhohacks/face-api.js@0.22.2/weights'

_FACEAPI_LOCAL_LIB = '/eh_hr_face_kiosk/static/lib/face-api/face-api.min.js'
_FACEAPI_LOCAL_MODELS = '/eh_hr_face_kiosk/static/lib/face-api/models'


def _faceapi_vendored(module_root=None):
    """Return True when the operator has vendored the full face-api.js
    bundle (library + all seven model files, each non-empty) into
    static/lib/face-api/."""
    if module_root is None:
        module_root = os.path.dirname(os.path.dirname(__file__))
    lib = os.path.join(module_root, *_FACEAPI_LIB_REL.split('/'))
    try:
        if os.path.getsize(lib) <= 0:
            return False
        models_dir = os.path.join(module_root, 'static', 'lib', 'face-api', 'models')
        for name in _FACEAPI_MODEL_FILES:
            if os.path.getsize(os.path.join(models_dir, name)) <= 0:
                return False
    except OSError:
        return False
    return True


class EhHrKioskShellController(http.Controller):

    @http.route('/eh_hr/kiosk/<string:site_code>', type='http', auth='public', methods=['GET'], csrf=False)
    def kiosk_shell(self, site_code, **kwargs):
        Site = request.env['eh.hr.kiosk.site'].sudo()
        site = Site.search([
            ('code', '=', site_code),
            ('active', '=', True),
        ], limit=1)

        vendored = _faceapi_vendored()
        cdn_disabled = request.env['ir.config_parameter'].sudo().get_bool(
            'eh_hr_face_kiosk.disable_cdn_fallback')
        if vendored:
            faceapi_src = _FACEAPI_LOCAL_LIB
            faceapi_models = _FACEAPI_LOCAL_MODELS
        elif not cdn_disabled:
            faceapi_src = _FACEAPI_CDN_LIB
            faceapi_models = _FACEAPI_CDN_MODELS
            _logger.warning(
                "eh_hr_face_kiosk: face-api.js bundle is not vendored under "
                "static/lib/face-api/; the kiosk page is serving the pinned "
                "CDN fallback. Vendor the files with "
                "eh_hr_face_kiosk/tools/fetch_face_api.sh (see "
                "static/lib/face-api/README.md).")
        else:
            # Air-gapped policy: no CDN. Render the page anyway; the
            # template shows the setup-required panel.
            faceapi_src = _FACEAPI_LOCAL_LIB
            faceapi_models = _FACEAPI_LOCAL_MODELS
            _logger.error(
                "eh_hr_face_kiosk: face-api.js bundle is not vendored and "
                "the CDN fallback is disabled "
                "(eh_hr_face_kiosk.disable_cdn_fallback). The kiosk at %s "
                "cannot run until an operator runs "
                "eh_hr_face_kiosk/tools/fetch_face_api.sh.", site_code)

        return request.render('eh_hr_face_kiosk.kiosk_shell', {
            'site_code': site_code,
            'site_found': bool(site),
            'site_name': site.name if site else '',
            'company_name': site.company_id.name if site else '',
            'asset_v': _kiosk_asset_version(),
            'faceapi_vendored': vendored,
            'faceapi_cdn_disabled': cdn_disabled,
            'faceapi_setup_blocked': (not vendored) and cdn_disabled,
            'faceapi_src': faceapi_src,
            'faceapi_models': faceapi_models,
        })
