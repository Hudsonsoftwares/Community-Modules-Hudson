from odoo.addons.hr_attendance.controllers.main import HrAttendance
from odoo import http, _
from odoo.http import request
from odoo.exceptions import UserError
import math

class HrAttendanceEnhancement(HrAttendance):

    def _haversine(self, lat1, lon1, lat2, lon2):
        if not lat1 or not lon1 or not lat2 or not lon2:
            return float('inf')
        R = 6371e3 # metres
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = math.sin(delta_phi / 2.0) ** 2 + \
            math.cos(phi1) * math.cos(phi2) * \
            math.sin(delta_lambda / 2.0) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    def _check_radius(self, company, latitude, longitude):
        if company.attendance_radius_punching:
            if not latitude or not longitude:
                raise UserError(_("Location is required to mark attendance."))
            
            allowed_locations = company.attendance_location_ids
            if allowed_locations:
                valid = False
                for loc in allowed_locations:
                    distance = self._haversine(latitude, longitude, loc.latitude, loc.longitude)
                    if distance <= loc.radius:
                        valid = True
                        break
                if not valid:
                    raise UserError(_("You are outside the permitted radius to mark attendance."))

    def _inject_photo_and_action(self, employee, geo_ip_response, photo=False):
        # Override action change to inject photo
        # Odoo's _attendance_action_change creates or writes to the attendance record
        # We can pass the photo to geo_ip_response and override `hr.employee`'s method to handle it.
        if photo:
            if employee.attendance_state != 'checked_in':
                geo_ip_response['photo'] = photo
            else:
                geo_ip_response['photo_out'] = photo
        return employee.sudo()._attendance_action_change(geo_ip_response)

    @http.route('/hr_attendance/systray_check_in_out', type="jsonrpc", auth="user")
    def systray_attendance(self, latitude=False, longitude=False, photo=False):
        employee = request.env.user.employee_id
        self._check_radius(employee.company_id, latitude, longitude)
        
        geo_ip_response = self._get_geoip_response(mode='systray',
                                                  latitude=latitude,
                                                  longitude=longitude,
                                                  device_tracking_enabled=employee.company_id.attendance_device_tracking)
        
        self._inject_photo_and_action(employee, geo_ip_response, photo)
        return self._get_employee_info_response(employee)

    @http.route('/hr_attendance/attendance_barcode_scanned', type="jsonrpc", auth="public")
    def scan_barcode_with_geolocation(self, token, barcode, latitude=False, longitude=False, photo=False):
        company = self._get_company(token)
        if company:
            self._check_radius(company, latitude, longitude)
            employee = request.env['hr.employee'].sudo().search([('barcode', '=', barcode), ('company_id', '=', company.id)], limit=1)
            if employee:
                geo_ip_response = self._get_geoip_response('kiosk', latitude=latitude, longitude=longitude, device_tracking_enabled=company.attendance_device_tracking)
                self._inject_photo_and_action(employee, geo_ip_response, photo)
                return self._get_employee_info_response(employee)
        return {}

    @http.route('/hr_attendance/manual_selection', type="jsonrpc", auth="public")
    def manual_selection(self, token, employee_id, pin_code, latitude=False, longitude=False, photo=False):
        company = self._get_company(token)
        if company:
            self._check_radius(company, latitude, longitude)
            employee = request.env['hr.employee'].sudo().browse(employee_id)
            if employee.company_id == company and ((not company.attendance_kiosk_use_pin) or (employee.pin == pin_code)):
                geo_ip_response = self._get_geoip_response('kiosk', latitude=latitude, longitude=longitude, device_tracking_enabled=company.attendance_device_tracking)
                self._inject_photo_and_action(employee, geo_ip_response, photo)
                return self._get_employee_info_response(employee)
        return {}

    @http.route('/hudson_attendance/search_location', type="jsonrpc", auth="user")
    def search_location(self, query):
        if not query:
            return []
        import requests
        url = 'https://nominatim.openstreetmap.org/search'
        headers = {
            'User-Agent': 'HudsonERP-Attendance/1.0 (contact@hudson.internal)',
            'Accept': 'application/json',
        }
        params = {
            'q': query,
            'format': 'json',
            'limit': 5,
            'addressdetails': 1,
        }
        try:
            res = requests.get(url, params=params, headers=headers, timeout=6)
            if res.status_code == 200:
                data = res.json()
                results = []
                for item in data:
                    results.append({
                        'display_name': item.get('display_name', ''),
                        'lat': float(item.get('lat', 0.0)),
                        'lon': float(item.get('lon', 0.0)),
                    })
                return results
        except Exception:
            pass
        return []

