from odoo.addons.hr_attendance.controllers.main import HrAttendance
from odoo import http, fields, _
from odoo.http import request
from odoo.exceptions import UserError
import math
import requests
import base64
from datetime import datetime, timedelta

class HrAttendanceEnhancement(HrAttendance):

    def _haversine(self, lat1, lon1, lat2, lon2):
        if not lat1 or not lon1 or not lat2 or not lon2:
            return float('inf')
        R = 6371e3  # metres
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
                raise UserError(_("Location / GPS coordinates are required to mark attendance when Radius Punching is enabled. Please allow location permissions in your browser."))
            
            allowed_locations = company.attendance_location_ids
            if allowed_locations:
                valid = False
                min_distance = float('inf')
                closest_loc = None
                for loc in allowed_locations:
                    distance = self._haversine(latitude, longitude, loc.latitude, loc.longitude)
                    if distance < min_distance:
                        min_distance = distance
                        closest_loc = loc
                    if distance <= loc.radius:
                        valid = True
                        break
                if not valid:
                    allowed_names = ", ".join(allowed_locations.mapped('name'))
                    raise UserError(
                        _("You are outside the permitted radius to mark attendance.\n"
                          "Closest location: %s (%.0f meters away, allowed radius: %.0f meters).\n"
                          "Permitted locations: %s")
                        % (closest_loc.name if closest_loc else "", min_distance, closest_loc.radius if closest_loc else 0, allowed_names)
                    )

    @staticmethod
    def _get_user_attendance_data(employee):
        res = HrAttendance._get_user_attendance_data(employee)
        if employee:
            company = employee.company_id
            if company.attendance_radius_punching or company.enable_work_from_home:
                res['device_tracking_enabled'] = True

            # Work from home frontend telemetry configuration
            res['is_wfh_employee'] = employee.is_wfh_employee
            res['wfh_enabled'] = company.enable_work_from_home and employee.is_wfh_employee
            res['wfh_interval'] = int(company.wfh_tracking_interval or 10)
        return res

    def _inject_photo_and_action(self, employee, geo_ip_response, photo=False, wfh_data=None):
        if not geo_ip_response:
            geo_ip_response = {}
        if photo:
            if employee.attendance_state != 'checked_in':
                geo_ip_response['photo'] = photo
            else:
                geo_ip_response['photo_out'] = photo
        if wfh_data:
            geo_ip_response.update(wfh_data)

        return employee.sudo()._attendance_action_change(geo_ip_response)

    @http.route('/hr_attendance/systray_check_in_out', type="jsonrpc", auth="user")
    def systray_attendance(self, latitude=False, longitude=False, photo=False):
        employee = request.env.user.employee_id
        if not employee:
            raise UserError(_("No employee associated with current user."))
        
        company = employee.company_id
        wfh_data = {}

        # 1. WFH Schedule & Geofence Verification
        if company.enable_work_from_home and employee.is_wfh_employee:
            allowed, reason = employee.is_wfh_allowed_today()
            if not allowed:
                raise UserError(reason)

            wfh_data['is_wfh'] = True
            dist_home = float('inf')
            if latitude and longitude and employee.home_latitude and employee.home_longitude:
                dist_home = self._haversine(latitude, longitude, employee.home_latitude, employee.home_longitude)
                wfh_data['dist_home'] = round(dist_home, 1)

            home_radius = employee.home_radius or company.wfh_home_radius or 150.0
            if dist_home <= home_radius:
                wfh_data['wfh_status'] = 'verified_home'
            else:
                if company.wfh_enforce_home_radius and not company.wfh_allow_offsite_with_reason:
                    raise UserError(
                        _("You are outside your authorized home radius (%.0f meters away; allowed radius: %.0f meters). Check-in at home is mandatory.")
                        % (dist_home, home_radius)
                    )
                wfh_data['wfh_status'] = 'offsite'

        # 2. Company-wide office radius verification (only for non-WFH or if enforced)
        if not (company.enable_work_from_home and employee.is_wfh_employee):
            self._check_radius(company, latitude, longitude)

        tracking_enabled = company.attendance_device_tracking or company.attendance_radius_punching or company.enable_work_from_home
        geo_ip_response = self._get_geoip_response(
            mode='systray',
            latitude=latitude,
            longitude=longitude,
            device_tracking_enabled=tracking_enabled,
        )

        attendance = self._inject_photo_and_action(employee, geo_ip_response, photo, wfh_data=wfh_data)

        # 3. Update employee live telemetry & initial location log
        if latitude and longitude:
            employee.sudo().write({
                'last_known_latitude': latitude,
                'last_known_longitude': longitude,
                'last_location_update': fields.Datetime.now(),
            })
            # Log initial tracking event
            status_calc = 'at_home' if (wfh_data.get('wfh_status') == 'verified_home') else 'offsite'
            request.env['hr.employee.location.log'].sudo().create({
                'employee_id': employee.id,
                'attendance_id': attendance.id if attendance else False,
                'latitude': latitude,
                'longitude': longitude,
                'distance_from_home': wfh_data.get('dist_home', 0.0),
                'distance_from_checkin': 0.0,
                'status': status_calc,
                'ip_address': request.httprequest.remote_addr,
            })

        return self._get_employee_info_response(employee)

    @http.route('/hudson_attendance/wfh_heartbeat', type="jsonrpc", auth="user")
    def wfh_heartbeat(self, latitude, longitude, accuracy=0.0):
        """Periodic background telemetry sent by WFH employees while checked in."""
        employee = request.env.user.employee_id
        if not employee or not latitude or not longitude:
            return {'status': 'ignored'}

        # Calculate distances
        dist_home = 0.0
        if employee.home_latitude and employee.home_longitude:
            dist_home = round(self._haversine(latitude, longitude, employee.home_latitude, employee.home_longitude), 1)

        dist_checkin = 0.0
        last_att = employee.last_attendance_id
        if last_att and last_att.in_latitude and last_att.in_longitude:
            dist_checkin = round(self._haversine(latitude, longitude, last_att.in_latitude, last_att.in_longitude), 1)

        # Status
        home_radius = employee.home_radius or employee.company_id.wfh_home_radius or 150.0
        if dist_home <= home_radius:
            status = 'at_home'
        elif dist_home <= max(1000.0, home_radius * 2):
            status = 'near_home'
        else:
            status = 'offsite'

        # Update employee live position
        employee.sudo().write({
            'last_known_latitude': latitude,
            'last_known_longitude': longitude,
            'last_location_update': fields.Datetime.now(),
        })

        # Save to location logs
        request.env['hr.employee.location.log'].sudo().create({
            'employee_id': employee.id,
            'attendance_id': last_att.id if last_att else False,
            'latitude': latitude,
            'longitude': longitude,
            'accuracy': accuracy,
            'distance_from_home': dist_home,
            'distance_from_checkin': dist_checkin,
            'status': status,
            'ip_address': request.httprequest.remote_addr,
        })

        return {
            'status': 'success',
            'dist_home': dist_home,
            'dist_checkin': dist_checkin,
        }

    @http.route('/hudson_attendance/get_live_wfh_employees', type="jsonrpc", auth="user")
    def get_live_wfh_employees(self, period='live', date_from=False, date_to=False):
        """Fetch remote employees data, logs, and statistics for the Live Map & Analytics dashboard."""
        if not request.env.user.has_group('hr_attendance.group_hr_attendance_officer'):
            raise UserError(_("Access Denied: You do not have permissions to view remote employees tracking."))

        now = fields.Datetime.now()
        today_date = fields.Date.context_today(request.env.user)
        
        # 1. Determine time bounds based on period
        log_domain = []
        if period == 'today':
            today_start = datetime.combine(today_date, datetime.min.time())
            log_domain = [('timestamp', '>=', today_start)]
        elif period == 'week':
            start_of_week = today_date - timedelta(days=today_date.weekday())
            week_start = datetime.combine(start_of_week, datetime.min.time())
            log_domain = [('timestamp', '>=', week_start)]
        elif period == 'month':
            month_start = datetime(today_date.year, today_date.month, 1)
            log_domain = [('timestamp', '>=', month_start)]
        elif period == 'custom' and (date_from or date_to):
            if date_from:
                d_from = datetime.strptime(date_from, "%Y-%m-%d")
                log_domain.append(('timestamp', '>=', d_from))
            if date_to:
                d_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
                log_domain.append(('timestamp', '<=', d_to))

        # 2. Find currently checked-in employees via open attendance records
        open_attendances = request.env['hr.attendance'].sudo().search([('check_out', '=', False)])
        active_wfh_emps = open_attendances.employee_id.filtered(lambda e: e.is_wfh_employee)

        if period == 'live':
            employees_to_display = active_wfh_emps
        else:
            # For historical periods, include employees with activity in that period
            recent_logs = request.env['hr.employee.location.log'].sudo().search(log_domain, limit=500)
            emp_ids = list(set(recent_logs.mapped('employee_id.id') + active_wfh_emps.ids))
            employees_to_display = request.env['hr.employee'].sudo().browse(emp_ids).filtered(lambda e: e.is_wfh_employee)

        employee_data = []
        for emp in employees_to_display:
            att = emp.last_attendance_id
            check_in_str = att.check_in.strftime("%H:%M:%S") if att and att.check_in else ""
            
            # Safe photo extraction
            photo_b64 = False
            if att and att.check_in_photo:
                raw_photo = att.check_in_photo
                if isinstance(raw_photo, bytes):
                    try:
                        photo_b64 = raw_photo.decode('ascii')
                    except Exception:
                        photo_b64 = base64.b64encode(raw_photo).decode('ascii')
                else:
                    photo_b64 = str(raw_photo)

            lat = emp.last_known_latitude or (att.in_latitude if att else 0.0) or emp.home_latitude or 0.0
            lon = emp.last_known_longitude or (att.in_longitude if att else 0.0) or emp.home_longitude or 0.0

            is_active = emp.id in active_wfh_emps.ids

            emp_radius = emp.home_radius or emp.company_id.wfh_home_radius or 150.0

            employee_data.append({
                'id': emp.id,
                'name': emp.name,
                'job_title': emp.job_title or "",
                'department_name': emp.department_id.name if emp.department_id else "",
                'avatar_url': f"/web/image?model=hr.employee&id={emp.id}&field=avatar_128",
                'check_in_photo': photo_b64,
                'lat': lat,
                'lon': lon,
                'home_lat': emp.home_latitude or 0.0,
                'home_lon': emp.home_longitude or 0.0,
                'home_address': emp.home_address_name or "Not configured",
                'home_radius': emp_radius,
                'distance_from_home_m': emp.current_distance_from_home,
                'distance_from_checkin_m': emp.current_distance_from_checkin,
                'status': emp.wfh_location_status,
                'is_active': is_active,
                'check_in_time': check_in_str,
                'worked_hours': round(emp.hours_today, 2),
                'last_update': emp.last_location_update.strftime("%H:%M:%S") if emp.last_location_update else "",
            })

        # 3. Retrieve location movement logs for tabular and trail display
        logs_records = request.env['hr.employee.location.log'].sudo().search(log_domain, order='timestamp desc', limit=100)
        logs_data = []
        for l in logs_records:
            logs_data.append({
                'id': l.id,
                'employee_id': l.employee_id.id,
                'employee_name': l.employee_id.name,
                'avatar_url': f"/web/image?model=hr.employee&id={l.employee_id.id}&field=avatar_128",
                'timestamp': l.timestamp.strftime("%Y-%m-%d %H:%M:%S") if l.timestamp else "",
                'latitude': l.latitude,
                'longitude': l.longitude,
                'status': l.status,
                'distance_from_home_m': l.distance_from_home,
                'distance_from_checkin_m': l.distance_from_checkin,
                'address': l.address or "",
                'ip_address': l.ip_address or "",
            })

        # 4. Compute statistics for graphical view
        total_emps = len(employee_data)
        at_home_count = sum(1 for e in employee_data if e['status'] == 'at_home')
        near_home_count = sum(1 for e in employee_data if e['status'] == 'near_home')
        offsite_count = sum(1 for e in employee_data if e['status'] == 'offsite')
        unknown_count = total_emps - at_home_count - near_home_count - offsite_count

        dept_counts = {}
        for e in employee_data:
            dept = e['department_name'] or "General"
            dept_counts[dept] = dept_counts.get(dept, 0) + 1

        avg_dist = 0.0
        valid_dists = [e['distance_from_home_m'] for e in employee_data if e['distance_from_home_m'] > 0]
        if valid_dists:
            avg_dist = round(sum(valid_dists) / len(valid_dists), 1)

        company_radius = request.env.company.wfh_home_radius or 150.0

        stats = {
            'total': total_emps,
            'active_now': len(active_wfh_emps),
            'at_home': at_home_count,
            'near_home': near_home_count,
            'offsite': offsite_count,
            'unknown': unknown_count,
            'default_home_radius': company_radius,
            'at_home_pct': round((at_home_count / total_emps * 100) if total_emps else 0, 1),
            'offsite_pct': round((offsite_count / total_emps * 100) if total_emps else 0, 1),
            'avg_distance_home_m': avg_dist,
            'max_distance_home_m': max(valid_dists) if valid_dists else 0.0,
            'departments': [{'name': k, 'count': v} for k, v in dept_counts.items()],
        }

        return {
            'employees': employee_data,
            'logs': logs_data,
            'stats': stats,
        }

    @http.route('/hr_attendance/attendance_barcode_scanned', type="jsonrpc", auth="public")
    def scan_barcode_with_geolocation(self, token, barcode, latitude=False, longitude=False, photo=False):
        company = self._get_company(token)
        if company:
            self._check_radius(company, latitude, longitude)
            employee = request.env['hr.employee'].sudo().search([('barcode', '=', barcode), ('company_id', '=', company.id)], limit=1)
            if employee:
                tracking_enabled = company.attendance_device_tracking or company.attendance_radius_punching or company.enable_work_from_home
                geo_ip_response = self._get_geoip_response('kiosk', latitude=latitude, longitude=longitude, device_tracking_enabled=tracking_enabled)
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
                tracking_enabled = company.attendance_device_tracking or company.attendance_radius_punching or company.enable_work_from_home
                geo_ip_response = self._get_geoip_response('kiosk', latitude=latitude, longitude=longitude, device_tracking_enabled=tracking_enabled)
                self._inject_photo_and_action(employee, geo_ip_response, photo)
                return self._get_employee_info_response(employee)
        return {}

    @http.route('/hudson_attendance/search_location', type="jsonrpc", auth="user")
    def search_location(self, query):
        if not query:
            return []
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
