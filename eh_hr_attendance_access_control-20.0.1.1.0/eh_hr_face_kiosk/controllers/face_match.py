# -*- encoding: utf-8 -*-
"""Face match endpoint for the kiosk shell.

Authentication: X-EH-Kiosk-Token header (issued by the base module's
pairing flow). The token identifies the device, which identifies the
site, which identifies the company. Templates are scoped to that
company; cross-company match is impossible at this layer.

Body (JSON): {embedding: [128 floats], geofence?: {lat, lng, accuracy}}.
Response 200: see _build_response below.

The match itself is a normalised dot product (cosine similarity) over
all active templates for the company. The hot path is small in
practice (typical site holds dozens to low hundreds of employees);
performance work begins once a customer crosses ~2k templates per
company, at which point a faiss-style index is the right answer.
"""
import json
import logging
import math

from odoo import fields, http
from odoo.http import request

from odoo.addons.eh_hr_attendance_base.tools.client_address import client_bucket, client_ip

_logger = logging.getLogger(__name__)


def _client_user_agent():
    return request.httprequest.headers.get('User-Agent', '')[:255]


def _json_response(payload, status=200):
    return request.make_response(
        json.dumps(payload),
        headers=[('Content-Type', 'application/json')],
        status=status,
    )


def _get_device_by_token(token):
    if not token:
        return None
    Device = request.env['eh.hr.kiosk.terminal'].sudo()
    return Device.search([
        ('device_token', '=', token),
        ('active', '=', True),
    ], limit=1)


def _throttled(scope, key, limit):
    """Return a 429 JSON response if the caller is over budget, else None.
    DB-backed so a stolen device token cannot hammer the match endpoint."""
    if not request.env['eh.hr.rate.limit'].sudo().hit(scope, key, limit):
        return _json_response({'error': 'rate_limited'}, status=429)
    return None


def _haversine_meters(lat1, lng1, lat2, lng2):
    R = 6371008.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _normalise(vec):
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def _cosine_distance(a, b):
    """1 - cosine similarity. Both vectors assumed already normalised."""
    return 1.0 - sum(x * y for x, y in zip(a, b))


class EhHrFaceMatchController(http.Controller):

    @http.route('/eh_hr/kiosk/face/match', type='http', auth='public', methods=['POST'], csrf=False)
    def face_match(self, **kwargs):
        token = request.httprequest.headers.get('X-EH-Kiosk-Token')
        throttled = _throttled('face.match', token or client_bucket(), 60)
        if throttled:
            return throttled
        device = _get_device_by_token(token)
        if not device:
            return _json_response({'error': 'unauthorized'}, status=401)

        try:
            data = json.loads(request.httprequest.data)
        except (ValueError, TypeError):
            return _json_response({'error': 'invalid body'}, status=400)

        embedding = data.get('embedding')
        if not isinstance(embedding, list) or not embedding:
            return _json_response({'error': 'embedding must be a non-empty float array'}, status=400)
        if not all(isinstance(v, (int, float)) for v in embedding):
            return _json_response({'error': 'embedding must contain only numbers'}, status=400)

        company = device.company_id
        site = device.site_id

        # Geofence check (optional, per-site).
        geo = data.get('geofence') or {}
        if site.geofence_enabled:
            try:
                lat = float(geo.get('lat'))
                lng = float(geo.get('lng'))
            except (TypeError, ValueError):
                request.env['eh.hr.kiosk.event'].sudo().log(
                    'geofence_fail',
                    device_id=device.id,
                    ip_address=client_ip(),
                    notes='No geolocation provided by client',
                    company_id=company.id,
                )
                return _json_response({'match': False, 'reason': 'geofence_required'}, status=200)
            distance_m = _haversine_meters(site.geofence_lat, site.geofence_lng, lat, lng)
            if distance_m > (site.geofence_radius_m or 50):
                request.env['eh.hr.kiosk.event'].sudo().log(
                    'geofence_fail',
                    device_id=device.id,
                    ip_address=client_ip(),
                    notes='Distance %.0fm exceeds radius %sm' % (distance_m, site.geofence_radius_m),
                    company_id=company.id,
                )
                return _json_response({'match': False, 'reason': 'geofence_violation'}, status=200)
            request.env['eh.hr.kiosk.event'].sudo().log(
                'geofence_pass',
                device_id=device.id,
                ip_address=client_ip(),
                notes='Distance %.0fm' % distance_m,
                company_id=company.id,
            )

        Template = request.env['eh.hr.face.template'].sudo()
        candidates = Template.search([
            ('active', '=', True),
            ('company_id', '=', company.id),
            ('consent_id.state', '=', 'granted'),
        ])

        if not candidates:
            request.env['eh.hr.kiosk.event'].sudo().log(
                'match_fail',
                device_id=device.id,
                ip_address=client_ip(),
                notes='No active templates for company',
                company_id=company.id,
            )
            return _json_response({'match': False, 'reason': 'no_templates'})

        normalised_incoming = _normalise(list(map(float, embedding)))
        threshold = company.eh_hr_match_threshold or 0.55
        best_template = None
        best_distance = float('inf')

        for tpl in candidates:
            try:
                stored = tpl.get_embedding_as_list()
            except (ValueError, TypeError):
                continue
            if len(stored) != len(normalised_incoming):
                continue
            stored_norm = _normalise([float(v) for v in stored])
            distance = _cosine_distance(normalised_incoming, stored_norm)
            if distance < best_distance:
                best_distance = distance
                best_template = tpl

        request.env['eh.hr.kiosk.event'].sudo().log(
            'attempt_match',
            device_id=device.id,
            employee_id=best_template.employee_id.id if best_template else None,
            confidence=max(0.0, 1.0 - best_distance) if best_template else 0.0,
            ip_address=client_ip(),
            user_agent=_client_user_agent(),
            company_id=company.id,
        )

        if not best_template or best_distance > threshold:
            request.env['eh.hr.kiosk.event'].sudo().log(
                'match_fail',
                device_id=device.id,
                employee_id=best_template.employee_id.id if best_template else None,
                confidence=max(0.0, 1.0 - best_distance) if best_template else 0.0,
                ip_address=client_ip(),
                notes='Best distance %.4f exceeds threshold %.4f' % (best_distance, threshold),
                company_id=company.id,
            )
            if best_template:
                request.env['eh.hr.attendance.exception'].sudo().raise_exception(
                    employee=best_template.employee_id,
                    exception_type='identity_low_confidence',
                    severity='warning',
                    description='Kiosk match below threshold (distance %.4f)' % best_distance,
                )
            return _json_response({
                'match': False,
                'reason': 'below_threshold',
                'best_distance': round(best_distance, 4) if best_template else None,
            })

        # Match success. Toggle attendance.
        employee = best_template.employee_id
        Attendance = request.env['hr.attendance'].sudo()
        open_attendance = Attendance.search([
            ('employee_id', '=', employee.id),
            ('check_out', '=', False),
        ], limit=1, order='check_in desc')

        now = fields.Datetime.now()
        if open_attendance:
            open_attendance.write({'check_out': now})
            action = 'check_out'
            attendance = open_attendance
        else:
            attendance = Attendance.create({
                'employee_id': employee.id,
                'check_in': now,
            })
            action = 'check_in'

        request.env['eh.hr.kiosk.event'].sudo().log(
            'match_success',
            device_id=device.id,
            employee_id=employee.id,
            confidence=1.0 - best_distance,
            ip_address=client_ip(),
            company_id=company.id,
        )
        request.env['eh.hr.kiosk.event'].sudo().log(
            'attendance_in' if action == 'check_in' else 'attendance_out',
            device_id=device.id,
            employee_id=employee.id,
            ref_model='hr.attendance',
            ref_id=attendance.id,
            company_id=company.id,
        )

        return _json_response({
            'match': True,
            'employee_id': employee.id,
            'employee_name': employee.name,
            'confidence': round(1.0 - best_distance, 4),
            'attendance_id': attendance.id,
            'action': action,
            'site_code': site.code,
        })
