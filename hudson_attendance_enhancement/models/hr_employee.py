from odoo import SUPERUSER_ID, models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import BinaryBytes
import base64
import math
from datetime import datetime

# Odoo 20: an hr.employee field that is not on hr.employee.public and has no groups
# is "private". Non-HR users reading any employee then get "The fields ... are not
# available for employee public profiles" (even through prefetch, e.g. employee.name).
# These fields are only shown on the HR employee form; non-HR code paths (systray
# check-in, WFH heartbeat) read them with sudo().
HR_PRIVATE_GROUPS = 'hr.group_hr_user'


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    last_attendance_photo = fields.Binary(
        string="Last Attendance Photo",
        compute="_compute_last_attendance_photo", groups=HR_PRIVATE_GROUPS,
    )

    # -------------------------------------------------------------
    # Work From Home (WFH) Settings
    # -------------------------------------------------------------
    is_wfh_employee = fields.Boolean(
        string="Work From Home Allowed",
        default=False,
        help="Check this if the employee is authorized to work from home / remotely.", groups=HR_PRIVATE_GROUPS,
    )
    wfh_type = fields.Selection([
        ('full_time', 'Full-Time Remote (Everyday)'),
        ('hybrid_days', 'Hybrid (Specific Days of the Week)'),
        ('hybrid_count', 'Hybrid (Days per Week)'),
        ('temporary', 'Temporary / Date Range'),
    ], string="WFH Arrangement", default='full_time', groups=HR_PRIVATE_GROUPS)

    # Specific days for hybrid schedule
    wfh_monday = fields.Boolean('Monday', default=True, groups=HR_PRIVATE_GROUPS)
    wfh_tuesday = fields.Boolean('Tuesday', default=True, groups=HR_PRIVATE_GROUPS)
    wfh_wednesday = fields.Boolean('Wednesday', default=True, groups=HR_PRIVATE_GROUPS)
    wfh_thursday = fields.Boolean('Thursday', default=True, groups=HR_PRIVATE_GROUPS)
    wfh_friday = fields.Boolean('Friday', default=True, groups=HR_PRIVATE_GROUPS)
    wfh_saturday = fields.Boolean('Saturday', default=False, groups=HR_PRIVATE_GROUPS)
    wfh_sunday = fields.Boolean('Sunday', default=False, groups=HR_PRIVATE_GROUPS)

    # Days count limit
    wfh_max_days_per_week = fields.Integer(string="Max WFH Days / Week", default=3, groups=HR_PRIVATE_GROUPS)

    # Temporary WFH date range
    wfh_date_from = fields.Date(string="WFH Valid From", groups=HR_PRIVATE_GROUPS)
    wfh_date_to = fields.Date(string="WFH Valid To", groups=HR_PRIVATE_GROUPS)

    # Approved Home Location
    home_latitude = fields.Float(string="Home Latitude", digits=(10, 7), groups=HR_PRIVATE_GROUPS)
    home_longitude = fields.Float(string="Home Longitude", digits=(10, 7), groups=HR_PRIVATE_GROUPS)
    home_address_name = fields.Char(string="Home Address Note / Label", groups=HR_PRIVATE_GROUPS)
    custom_home_radius = fields.Float(
        string="Custom Home Radius (m)",
        default=0.0,
        help="Specific allowed radius for this employee in meters. Set to 0 to use the company-wide default.", groups=HR_PRIVATE_GROUPS,
    )
    home_radius = fields.Float(
        string="Allowed Home Radius (m)",
        compute="_compute_home_radius",
        inverse="_inverse_home_radius",
        store=True,
        help="Effective allowed radius around approved home geofence.", groups=HR_PRIVATE_GROUPS,
    )

    @api.depends('custom_home_radius', 'company_id.wfh_home_radius')
    def _compute_home_radius(self):
        for emp in self:
            if emp.custom_home_radius and emp.custom_home_radius > 0:
                emp.home_radius = emp.custom_home_radius
            else:
                emp.home_radius = emp.company_id.wfh_home_radius or 150.0

    def _inverse_home_radius(self):
        for emp in self:
            emp.custom_home_radius = emp.home_radius

    # Live Real-Time Telemetry & Tracking
    last_known_latitude = fields.Float(string="Last Known Latitude", digits=(10, 7), groups=HR_PRIVATE_GROUPS)
    last_known_longitude = fields.Float(string="Last Known Longitude", digits=(10, 7), groups=HR_PRIVATE_GROUPS)
    last_location_update = fields.Datetime(string="Last Location Update", groups=HR_PRIVATE_GROUPS)
    last_location_address = fields.Char(string="Last Detected Address", groups=HR_PRIVATE_GROUPS)
    location_log_ids = fields.One2many('hr.employee.location.log', 'employee_id', string="Location Logs", groups=HR_PRIVATE_GROUPS)
    location_log_count = fields.Integer(string="Location Logs Count", compute="_compute_location_log_count", groups=HR_PRIVATE_GROUPS)

    # Dynamic distance metrics
    current_distance_from_home = fields.Float(
        string="Distance from Home (m)",
        compute="_compute_wfh_distances",
        help="Current distance between last known location and registered home location.", groups=HR_PRIVATE_GROUPS,
    )
    current_distance_from_checkin = fields.Float(
        string="Distance from Check-In (m)",
        compute="_compute_wfh_distances",
        help="Current distance between last known location and where the employee first checked in today.", groups=HR_PRIVATE_GROUPS,
    )
    wfh_location_status = fields.Selection([
        ('at_home', 'At Home (< 150m)'),
        ('near_home', 'Near Home (< 1 km)'),
        ('offsite', 'Offsite / Away (> 1 km)'),
        ('unknown', 'No Location Data'),
    ], string="Current Location Status", compute="_compute_wfh_distances", groups=HR_PRIVATE_GROUPS)

    def _compute_location_log_count(self):
        log_data = self.env['hr.employee.location.log']._read_group(
            [('employee_id', 'in', self.ids)],
            ['employee_id'],
            ['__count'],
        )
        mapped = {employee.id: count for employee, count in log_data}
        for employee in self:
            employee.location_log_count = mapped.get(employee.id, 0)

    @api.depends('last_attendance_id.in_image', 'last_attendance_id.out_image')
    def _compute_last_attendance_photo(self):
        for employee in self:
            att = employee.last_attendance_id.sudo()
            image = att.out_image or att.in_image
            employee.last_attendance_photo = base64.b64encode(bytes(image)).decode() if image else False

    def _haversine(self, lat1, lon1, lat2, lon2):
        if not lat1 or not lon1 or not lat2 or not lon2:
            return float('inf')
        R = 6371e3
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        a = math.sin(delta_phi / 2.0) ** 2 + \
            math.cos(phi1) * math.cos(phi2) * \
            math.sin(delta_lambda / 2.0) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _compute_wfh_distances(self):
        for employee in self:
            lat = employee.last_known_latitude
            lon = employee.last_known_longitude

            if not lat or not lon:
                employee.current_distance_from_home = 0.0
                employee.current_distance_from_checkin = 0.0
                employee.wfh_location_status = 'unknown'
                continue

            # Distance from home
            home_dist = float('inf')
            if employee.home_latitude and employee.home_longitude:
                home_dist = self._haversine(lat, lon, employee.home_latitude, employee.home_longitude)
                employee.current_distance_from_home = round(home_dist, 1)
            else:
                employee.current_distance_from_home = 0.0

            # Distance from check-in
            checkin_dist = 0.0
            last_att = employee.last_attendance_id
            if last_att and last_att.in_latitude and last_att.in_longitude:
                checkin_dist = self._haversine(lat, lon, last_att.in_latitude, last_att.in_longitude)
                employee.current_distance_from_checkin = round(checkin_dist, 1)
            else:
                employee.current_distance_from_checkin = 0.0

            # Status classification
            home_radius = employee.home_radius or employee.company_id.wfh_home_radius or 150.0
            if home_dist <= home_radius:
                employee.wfh_location_status = 'at_home'
            elif home_dist <= max(1000.0, home_radius * 2):
                employee.wfh_location_status = 'near_home'
            elif home_dist < float('inf'):
                employee.wfh_location_status = 'offsite'
            else:
                employee.wfh_location_status = 'unknown'

    def is_wfh_allowed_today(self):
        """Verify whether employee is permitted to work from home on the current day."""
        self.ensure_one()
        if not self.is_wfh_employee:
            return False, _("Work From Home is not enabled for your profile.")

        today = fields.Date.context_today(self)
        weekday = today.weekday()  # 0=Monday, 6=Sunday

        if self.wfh_type == 'full_time':
            return True, ""

        elif self.wfh_type == 'hybrid_days':
            allowed_days = {
                0: self.wfh_monday,
                1: self.wfh_tuesday,
                2: self.wfh_wednesday,
                3: self.wfh_thursday,
                4: self.wfh_friday,
                5: self.wfh_saturday,
                6: self.wfh_sunday,
            }
            if allowed_days.get(weekday, False):
                return True, ""
            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            today_name = day_names[weekday]
            allowed_names = [day_names[d] for d, allowed in allowed_days.items() if allowed]
            return False, _("Today (%s) is not an authorized WFH day. Approved days: %s") % (today_name, ", ".join(allowed_names))

        elif self.wfh_type == 'temporary':
            if self.wfh_date_from and today < self.wfh_date_from:
                return False, _("WFH arrangement begins on %s.") % self.wfh_date_from
            if self.wfh_date_to and today > self.wfh_date_to:
                return False, _("WFH arrangement expired on %s.") % self.wfh_date_to
            return True, ""

        elif self.wfh_type == 'hybrid_count':
            # Check attendances marked as WFH this week
            start_of_week = today - fields.Date.to_date(datetime.now().strftime('%Y-%m-%d')).weekday()
            wfh_attendances = self.env['hr.attendance'].search_count([
                ('employee_id', '=', self.id),
                ('is_wfh', '=', True),
                ('check_in', '>=', fields.Datetime.to_datetime(start_of_week)),
            ])
            if wfh_attendances >= self.wfh_max_days_per_week:
                return False, _("You have reached your limit of %s WFH days for this week.") % self.wfh_max_days_per_week
            return True, ""

        return True, ""

    def action_set_home_from_last_location(self):
        """Set registered home coordinates to employee's last known location."""
        self.ensure_one()
        if not self.last_known_latitude or not self.last_known_longitude:
            raise UserError(_("No GPS location has been detected yet for this employee."))
        self.write({
            'home_latitude': self.last_known_latitude,
            'home_longitude': self.last_known_longitude,
            'home_address_name': self.last_location_address or _("Captured from Device Location"),
        })

    def action_fetch_home_from_private_address(self):
        """Fetch and geocode coordinates using the Private Address from the Personal Information tab."""
        self.ensure_one()
        addr_parts = [
            self.private_street,
            self.private_street2,
            self.private_city,
            self.private_state_id.name if self.private_state_id else False,
            self.private_zip,
            self.private_country_id.name if self.private_country_id else False,
        ]
        valid_parts = [str(p).strip() for p in addr_parts if p and str(p).strip()]
        if not valid_parts:
            raise UserError(_("No private address found in the 'Personal Information' tab. Please fill in the employee's private address first."))

        full_address = ", ".join(valid_parts)
        
        import requests
        url = 'https://nominatim.openstreetmap.org/search'
        headers = {
            'User-Agent': 'HudsonERP-Attendance/1.0 (contact@hudson.internal)',
            'Accept': 'application/json',
        }

        lat, lon, display_name = False, False, False
        try:
            res = requests.get(url, params={'q': full_address, 'format': 'json', 'limit': 1}, headers=headers, timeout=6)
            if res.status_code == 200 and res.json():
                data = res.json()[0]
                lat = float(data.get('lat', 0.0))
                lon = float(data.get('lon', 0.0))
                display_name = data.get('display_name', full_address)
        except Exception:
            pass

        # If exact address query failed, try city + country fallback
        if not lat and not lon and (self.private_city or self.private_country_id):
            fallback_parts = [self.private_city, self.private_country_id.name if self.private_country_id else False]
            fallback_query = ", ".join([p for p in fallback_parts if p])
            try:
                res = requests.get(url, params={'q': fallback_query, 'format': 'json', 'limit': 1}, headers=headers, timeout=6)
                if res.status_code == 200 and res.json():
                    data = res.json()[0]
                    lat = float(data.get('lat', 0.0))
                    lon = float(data.get('lon', 0.0))
                    display_name = full_address
            except Exception:
                pass

        if not lat and not lon:
            raise UserError(
                _("Could not automatically resolve GPS coordinates for '%s'. Please select or search the location using the interactive map.")
                % full_address
            )

        self.write({
            'home_latitude': lat,
            'home_longitude': lon,
            'home_address_name': display_name or full_address,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Home Location Detected"),
                'message': _("Successfully set home coordinates to %s (%.6f, %.6f)") % (full_address, lat, lon),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_view_location_logs(self):
        """Open location history logs for this employee."""
        self.ensure_one()
        return {
            'name': _("Location History: %s") % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.location.log',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

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

    def _attendance_action_change(self, geo_information=None, check_in_image_data=None,
                                  check_out_image_data=None, wfh_data=None):
        """Odoo 20 check in/out, extended with:

        - a check-out picture, stored in ``out_image`` and posted in the chatter
          exactly like core does for the check-in picture (``in_image``);
        - the Work From Home verification data computed by the controller.
        """
        self.ensure_one()
        wfh_data = wfh_data or {}
        Attendance = self.env['hr.attendance']
        open_domain = [('employee_id', '=', self.id), ('check_out', '=', False)]
        checking_out = self.attendance_state == 'checked_in'
        attendance = Attendance.search(open_domain, limit=1) if checking_out else Attendance

        notification = super()._attendance_action_change(geo_information, check_in_image_data)

        if not checking_out:
            attendance = Attendance.search(open_domain, order='check_in desc', limit=1)
            if check_in_image_data and not self.image_1920:
                self.sudo().image_1920 = base64.b64encode(check_in_image_data['image']).decode()
        elif attendance and attendance.check_out:
            if check_out_image_data:
                attendance.sudo().out_image = BinaryBytes(check_out_image_data['image'])
                attachment = self.env['ir.attachment'].sudo().search([
                    ('res_model', '=', attendance._name),
                    ('res_id', '=', attendance.id),
                    ('res_field', '=', 'out_image'),
                ], limit=1)
                attachment.name = f"{self.display_name.replace(' ', '_')}_{str(attendance.check_out).replace(' ', '_')}_UTC_out"
                message_vals = {
                    'body': self.env._("Check-out image captured"),
                    'attachment_ids': [attachment.id],
                }
                if self.env.user._is_internal():
                    attendance.message_post(**message_vals)
                else:
                    attendance.with_user(SUPERUSER_ID).message_post(**message_vals)
            elif self.company_id.attendance_capture_check_out and not notification:
                notification = {
                    'type': 'warning',
                    'message': self.env._("Check-out is recorded, but picture could not be captured"),
                }

        if attendance and wfh_data:
            vals = {}
            if wfh_data.get('is_wfh'):
                vals['is_wfh'] = True
            if wfh_data.get('wfh_status'):
                vals['wfh_status'] = wfh_data['wfh_status']
            if wfh_data.get('offsite_reason'):
                vals['wfh_offsite_reason'] = wfh_data['offsite_reason']
            if 'dist_home' in wfh_data:
                key = 'check_out_distance_from_home' if checking_out else 'check_in_distance_from_home'
                vals[key] = wfh_data['dist_home']
            if vals:
                attendance.sudo().write(vals)

        return notification
