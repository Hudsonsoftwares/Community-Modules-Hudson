# -*- encoding: utf-8 -*-
"""Access trigger endpoint. Called by the kiosk JS after a successful
face match (the access_trigger.js module wraps the match endpoint).
The endpoint resolves the employee, the device's zone, the active
reader, validates the permission, calls the reader's webhook, and
records an `eh.hr.access.event` row regardless of outcome.
"""
import json

from odoo import http
from odoo.http import request

from odoo.addons.eh_hr_attendance_base.tools.client_address import client_bucket


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
    """Return a 429 JSON response if the caller is over budget, else None."""
    if not request.env['eh.hr.rate.limit'].sudo().hit(scope, key, limit):
        return _json_response({'error': 'rate_limited'}, status=429)
    return None


class EhHrAccessController(http.Controller):

    @http.route('/eh_hr/kiosk/access/trigger', type='http', auth='public', methods=['POST'], csrf=False)
    def trigger(self, **kwargs):
        token = request.httprequest.headers.get('X-EH-Kiosk-Token')
        throttled = _throttled('access.trigger', token or client_bucket(), 60)
        if throttled:
            return throttled
        device = _get_device_by_token(token)
        if not device:
            return _json_response({'error': 'unauthorized'}, status=401)

        try:
            data = json.loads(request.httprequest.data)
        except (ValueError, TypeError):
            return _json_response({'error': 'invalid body'}, status=400)

        try:
            employee_id = int(data.get('employee_id'))
        except (TypeError, ValueError):
            return _json_response({'error': 'employee_id is required and must be an integer'}, status=400)

        Employee = request.env['hr.employee'].sudo()
        employee = Employee.browse(employee_id).exists()
        if not employee or employee.company_id != device.company_id:
            return _json_response({'error': 'employee not found'}, status=404)

        Zone = request.env['eh.hr.access.zone'].sudo()
        zones = Zone.search([
            ('site_ids', '=', device.site_id.id),
            ('company_id', '=', device.company_id.id),
            ('active', '=', True),
        ])

        Event = request.env['eh.hr.access.event'].sudo()

        if not zones:
            event = Event.create({
                'employee_id': employee.id,
                'site_id': device.site_id.id,
                'device_id': device.id,
                'outcome': 'no_zone',
                'company_id': device.company_id.id,
            })
            return _json_response({'ok': False, 'reason': 'no_zone', 'event_id': event.id})

        # First zone wins. Multi-zone-per-site is a Wave 2 enhancement.
        zone = zones[0]

        Permission = request.env['eh.hr.access.permission'].sudo()
        permission = Permission.search([
            ('employee_id', '=', employee.id),
            ('zone_id', '=', zone.id),
            ('active', '=', True),
        ], limit=1)
        if not permission or not permission.is_currently_valid():
            event = Event.create({
                'employee_id': employee.id,
                'zone_id': zone.id,
                'site_id': device.site_id.id,
                'device_id': device.id,
                'outcome': 'denied',
                'company_id': device.company_id.id,
            })
            return _json_response({'ok': False, 'reason': 'denied', 'event_id': event.id})

        reader = zone.reader_ids.filtered('active')[:1]
        if not reader:
            event = Event.create({
                'employee_id': employee.id,
                'zone_id': zone.id,
                'site_id': device.site_id.id,
                'device_id': device.id,
                'outcome': 'no_reader',
                'company_id': device.company_id.id,
            })
            return _json_response({'ok': False, 'reason': 'no_reader', 'event_id': event.id})

        status, elapsed_ms, response = reader.trigger_unlock(
            employee=employee,
            reason='kiosk_face_match',
        )
        outcome_map = {'ok': 'allowed', 'denied': 'reader_denied', 'error': 'reader_error'}
        outcome = outcome_map.get(status, 'reader_error')

        event = Event.create({
            'employee_id': employee.id,
            'zone_id': zone.id,
            'reader_id': reader.id,
            'site_id': device.site_id.id,
            'device_id': device.id,
            'outcome': outcome,
            'reader_response': response,
            'elapsed_ms': elapsed_ms,
            'company_id': device.company_id.id,
        })

        return _json_response({
            'ok': outcome == 'allowed',
            'outcome': outcome,
            'reader': reader.name,
            'event_id': event.id,
            'elapsed_ms': elapsed_ms,
        })
