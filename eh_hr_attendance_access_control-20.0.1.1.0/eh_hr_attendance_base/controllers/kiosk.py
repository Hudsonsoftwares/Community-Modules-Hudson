# -*- encoding: utf-8 -*-
"""Kiosk shell controllers for the EH attendance suite.

This module owns the device pairing and heartbeat surface. It does not
own the actual capture / match UI, which lives in the matching modality
module (eh_hr_face_kiosk for face, future eh_hr_fp_kiosk for
fingerprint, etc.) so multiple capture types can share one device
registry, one site model, and one audit trail.

Authentication model
--------------------

* Pairing endpoint uses a one-time pairing code that an admin generates
  in Odoo and reads aloud (or scans as QR) on the kiosk during setup.
  The code is short-lived and single-use. The server, on success,
  issues a long opaque device_token.
* Every other endpoint requires the device_token in the X-EH-Kiosk-Token
  header. A revoked or unknown token returns 401.
* Endpoints are rate-limited per IP via Odoo's standard `routes` rate
  limit when present; otherwise we apply a soft per-token cap by
  recording last_seen and rejecting bursts shorter than 1 second.
* The pairing endpoint is public and the site code is printed in the kiosk
  URL, so the PIN is guarded against guessing, in a way that cannot be
  turned against the real kiosk:

  * A client gets _PAIR_LIMIT_PER_MIN attempts a minute (429 beyond that,
    the mobile pair route's budget). A client is the address Odoo's HTTP
    layer resolved (client_ip()), counted per /64 for IPv6
    (client_bucket()), the rule eh_hr_attendance_base/tools/client_address
    writes for every public route. A header the caller writes itself never
    makes it a new client.
  * A client's attempts spend its own budget only, never the site's, so no
    single address can hold a site at 429.
  * Each outstanding PIN counts the wrong PINs sent for its site since it
    was issued, and is withdrawn once it has taken more than one client
    can send while it is live (_PAIR_MAX_FAILURES). So one address never
    withdraws a PIN, a PIN issued later starts from zero, and a guesser
    gets at most _PAIR_MAX_FAILURES + 1 tries at a million values per PIN,
    however many addresses it uses. A withdrawal writes an 'error' audit
    event naming the site, which the admin reads in the event log.
  * One hold of the lock decides an attempt: the PIN is looked up, then
    claimed when it is right, or the wrong guess counted and a PIN past its
    limit withdrawn, before any other request may look a PIN up. So a
    threaded server never checks more guesses against a PIN than its limit.

  The trade off: a guesser with several addresses can still get a live PIN
  withdrawn, by sending more wrong PINs for its site than one client may,
  and by keeping that up it gets each new PIN withdrawn too, so the site
  cannot pair while the guessing lasts (about 13 addresses withdraw a PIN
  within half a minute). It never pairs a terminal, and the admin sees each
  withdrawal in the event log. A client behind the same address as the
  kiosk (one office NAT) shares its budget, and a deployment behind a
  reverse proxy must run with proxy_mode and have the proxy send
  X-Forwarded-For and X-Forwarded-Host, as Odoo's own deployment guide
  asks, or every client is the proxy.
"""
import json
import logging
import threading
import time
from datetime import UTC

from odoo import _, http
from odoo.http import request

from odoo.addons.eh_hr_attendance_base.tools.client_address import client_bucket, client_ip

_logger = logging.getLogger(__name__)


# In-memory pairing PIN cache. PINs are short-lived (5 min) and stored
# in this process only, which is acceptable because pairing is a manual step
# that an admin and the kiosk operator perform together. For
# multi-worker deployments the admin retries on the worker that holds
# the PIN, or the eh_hr_face_kiosk module can later promote this to
# ir.config_parameter.
_PAIRING_PINS = {}
_PAIRING_TTL_SECONDS = 300
_MIN_HEARTBEAT_INTERVAL = 1.0

# Guessing guard for the pair route. The counters live in this process, next
# to the PINs they protect: a PIN can only be redeemed on the worker that
# holds it, and that worker counts every attempt that could redeem it. A
# restart clears both. One lock covers the PINs and the counters, so a PIN is
# claimed, withdrawn or guessed by one request at a time.
_PAIR_LIMIT_PER_MIN = 10
_PAIR_WINDOW_SECONDS = 60
# Wrong PINs a live PIN survives: what one client can send while the PIN is
# live, its budget for every window the PIN's life touches (10 x 6). Only
# more than that, which takes several addresses, withdraws the PIN.
_PAIR_MAX_FAILURES = _PAIR_LIMIT_PER_MIN * (_PAIRING_TTL_SECONDS // _PAIR_WINDOW_SECONDS + 1)
_PAIR_LOCK = threading.Lock()
# client bucket -> timestamps of its attempts inside the sliding window
_PAIR_ATTEMPTS = {}
_PAIR_PRUNED_AT = 0.0


def _now():
    return time.time()


def _expire_pairing_pins():
    with _PAIR_LOCK:
        cutoff = _now() - _PAIRING_TTL_SECONDS
        stale = [pin for pin, info in _PAIRING_PINS.items() if info['issued_at'] < cutoff]
        for pin in stale:
            _PAIRING_PINS.pop(pin, None)


def _pair_over_budget(key):
    """Count one pairing attempt against the client ``key`` and return True
    when it already spent _PAIR_LIMIT_PER_MIN attempts in the last
    _PAIR_WINDOW_SECONDS. A refused attempt is not counted, so the budget
    comes back a minute after the burst, not a minute after the last try.
    Nothing else is charged: no site has a budget a client could spend.
    """
    global _PAIR_PRUNED_AT
    now = _now()
    cutoff = now - _PAIR_WINDOW_SECONDS
    with _PAIR_LOCK:
        # Buckets of callers gone quiet are dropped once a window, so the
        # table never holds more than one window of clients.
        if now - _PAIR_PRUNED_AT >= _PAIR_WINDOW_SECONDS:
            for bucket in [b for b, stamps in _PAIR_ATTEMPTS.items() if stamps[-1] <= cutoff]:
                del _PAIR_ATTEMPTS[bucket]
            _PAIR_PRUNED_AT = now
        bucket = (key or 'anon')[:128]
        stamps = [stamp for stamp in _PAIR_ATTEMPTS.get(bucket, ()) if stamp > cutoff]
        over = len(stamps) >= _PAIR_LIMIT_PER_MIN
        if not over:
            stamps.append(now)
        _PAIR_ATTEMPTS[bucket] = stamps
        return over


def _pair_failed(site_code):
    """Count one wrong PIN sent for site_code against every PIN outstanding
    for that site, withdraw the ones that have now taken more than
    _PAIR_MAX_FAILURES, and return how many were withdrawn. The caller holds
    _PAIR_LOCK, the hold in which it looked the wrong PIN up.

    The count belongs to each PIN, not to the site: a PIN issued while the
    site is being guessed starts from zero and outlives the one under
    attack. A site with no outstanding PIN has nothing to guess and keeps
    no count, so made up site codes cost no memory."""
    withdrawn = 0
    for pin, info in list(_PAIRING_PINS.items()):
        if info['site_code'] != site_code:
            continue
        info['failures'] = info.get('failures', 0) + 1
        if info['failures'] > _PAIR_MAX_FAILURES:
            del _PAIRING_PINS[pin]
            withdrawn += 1
    return withdrawn


def _get_device_by_token(token):
    if not token:
        return None
    Device = request.env['eh.hr.kiosk.terminal'].sudo()
    return Device.search([
        ('device_token', '=', token),
        ('active', '=', True),
    ], limit=1)


def _client_user_agent():
    return request.httprequest.headers.get('User-Agent', '')[:255]


def _json_response(payload, status=200):
    return request.make_response(
        json.dumps(payload),
        headers=[('Content-Type', 'application/json')],
        status=status,
    )


class EhHrKioskController(http.Controller):

    @http.route('/eh_hr/kiosk/pair', type='http', auth='public', methods=['POST'], csrf=False)
    def pair(self, **kwargs):
        """Trade a one-time pairing PIN for a long-lived device token.

        Body (JSON or form): site_code, pin, device_name (optional).
        Response 200: {device_token, site_id, site_name}.
        Response 4xx: {error}.

        The PIN is generated by an admin in Odoo via the kiosk site
        action. It is one-shot and expires after PAIRING_TTL_SECONDS.

        Response 429 {error: 'rate_limited'} once the client has spent its
        attempts for the minute; no other client's attempts count against
        it. Every refused PIN gets the same 403, whether it is unknown,
        expired, withdrawn or live for another site, so a guess that lands
        on another site's PIN tells the guesser nothing and is charged to
        the site it was sent for.
        """
        _expire_pairing_pins()
        if _pair_over_budget(client_bucket()):
            return _json_response({'error': 'rate_limited'}, status=429)
        try:
            data = json.loads(request.httprequest.data) if request.httprequest.data else {}
        except ValueError:
            data = {}
        data = {**kwargs, **data}

        site_code = (data.get('site_code') or '').strip()
        pin = (data.get('pin') or '').strip()
        device_name = (data.get('device_name') or '').strip() or _('Unnamed kiosk')

        if not site_code or not pin:
            return _json_response({'error': 'site_code and pin are required'}, status=400)

        Site = request.env['eh.hr.kiosk.site'].sudo()
        site = Site.search([('code', '=', site_code), ('active', '=', True)], limit=1)
        # One hold of the lock decides the attempt. Checked in one hold and
        # counted in the next, requests served in between on a threaded
        # server were checked against a PIN that a guess ahead of them was
        # about to withdraw, so more guesses than _PAIR_MAX_FAILURES + 1
        # reached a live PIN. The PIN is claimed in the same hold, so that of
        # two requests carrying it only one pairs.
        claimed = None
        withdrawn = 0
        with _PAIR_LOCK:
            info = _PAIRING_PINS.get(pin)
            valid = bool(info) and info['site_code'] == site_code \
                and info['issued_at'] + _PAIRING_TTL_SECONDS >= _now()
            if not valid:
                withdrawn = _pair_failed(site_code)
            elif site:
                claimed = _PAIRING_PINS.pop(pin)
        if not valid:
            if withdrawn:
                company = Site.search([('code', '=', site_code)], limit=1).company_id
                _logger.info(
                    "Kiosk pairing: %s PIN(s) for site %r withdrawn after more than %s wrong PINs",
                    withdrawn, site_code, _PAIR_MAX_FAILURES)
                request.env['eh.hr.kiosk.event'].sudo().log(
                    'error',
                    ip_address=client_ip(),
                    user_agent=_client_user_agent(),
                    notes='Pairing PIN for site %s withdrawn: it took more than %s wrong PINs '
                          'while it was live, more than any single client is allowed to send, '
                          'so it was being guessed from several addresses. No terminal was '
                          'paired with it. Issue a new PIN to pair a kiosk.'
                          % (site_code, _PAIR_MAX_FAILURES),
                    company_id=company.id or None,
                )
            return _json_response({'error': 'Invalid or expired pairing PIN'}, status=403)

        if not claimed:
            # The PIN is right but its site is gone or archived: it stays
            # outstanding, as it did, and pairs nothing.
            return _json_response({'error': 'Unknown or inactive site'}, status=404)

        Device = request.env['eh.hr.kiosk.terminal'].sudo()
        device = Device.create({
            'name': device_name,
            'site_id': site.id,
            'last_ip': client_ip(),
            'user_agent': _client_user_agent(),
        })

        request.env['eh.hr.kiosk.event'].sudo().log(
            'device_register',
            device_id=device.id,
            ip_address=client_ip(),
            user_agent=_client_user_agent(),
            notes='Device paired via /eh_hr/kiosk/pair',
            company_id=site.company_id.id,
        )

        return _json_response({
            'device_token': device.device_token,
            'site_id': site.id,
            'site_name': site.name,
            'site_code': site.code,
        })

    @http.route('/eh_hr/kiosk/heartbeat', type='http', auth='public', methods=['POST'], csrf=False)
    def heartbeat(self, **kwargs):
        """Record a kiosk heartbeat. Returns 200 OK with site config.

        Auth: X-EH-Kiosk-Token header.
        Body: ignored.
        """
        token = request.httprequest.headers.get('X-EH-Kiosk-Token')
        device = _get_device_by_token(token)
        if not device:
            return _json_response({'error': 'unauthorized'}, status=401)

        # last_seen is a naive UTC value. Odoo forces the process timezone to
        # UTC, so stamping it explicitly changes nothing at runtime and keeps
        # the comparison with the epoch clock correct on its own terms.
        last_seen_ts = device.last_seen.replace(tzinfo=UTC).timestamp() if device.last_seen else 0
        if last_seen_ts and _now() - last_seen_ts < _MIN_HEARTBEAT_INTERVAL:
            return _json_response({'error': 'rate limited'}, status=429)

        device._touch(ip_address=client_ip(), user_agent=_client_user_agent())

        request.env['eh.hr.kiosk.event'].sudo().log(
            'device_heartbeat',
            device_id=device.id,
            ip_address=client_ip(),
            company_id=device.company_id.id,
        )

        company = device.company_id
        return _json_response({
            'site_code': device.site_id.code,
            'site_name': device.site_id.name,
            'idle_seconds': company.eh_hr_kiosk_idle_seconds or 30,
            'match_threshold': company.eh_hr_match_threshold or 0.55,
            'geofence': {
                'enabled': bool(device.site_id.geofence_enabled),
                'lat': device.site_id.geofence_lat,
                'lng': device.site_id.geofence_lng,
                'radius_m': device.site_id.geofence_radius_m,
            },
        })

    @http.route('/eh_hr/kiosk/whoami', type='http', auth='public', methods=['GET'], csrf=False)
    def whoami(self, **kwargs):
        """Return device + site identity for the calling token. Used for
        kiosk shell bootstrap before the matching modality loads.
        """
        token = request.httprequest.headers.get('X-EH-Kiosk-Token')
        device = _get_device_by_token(token)
        if not device:
            return _json_response({'error': 'unauthorized'}, status=401)
        return _json_response({
            'device_id': device.id,
            'device_name': device.name,
            'site_code': device.site_id.code,
            'site_name': device.site_id.name,
            'company_id': device.company_id.id,
            'idle_seconds': device.company_id.eh_hr_kiosk_idle_seconds or 30,
        })


def issue_pairing_pin(site_code):
    """Server-side helper for the kiosk site form's "Pair a new device"
    button (added by the kiosk_site form action). Returns a freshly
    generated 6-digit PIN that is valid for PAIRING_TTL_SECONDS.

    Kept module-level so other EH HR modules can reuse the same in-memory
    pairing store rather than spinning up their own.
    """
    import secrets as _secrets
    _expire_pairing_pins()
    pin = ''.join(_secrets.choice('0123456789') for _ in range(6))
    with _PAIR_LOCK:
        # A new PIN starts its own count of wrong guesses; the site's other
        # outstanding PINs keep theirs.
        _PAIRING_PINS[pin] = {
            'site_code': site_code,
            'issued_at': _now(),
            'failures': 0,
        }
    return pin
