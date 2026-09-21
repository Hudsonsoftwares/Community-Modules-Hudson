from odoo import models, api, _
from odoo.exceptions import UserError
import math

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

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

    def _attendance_action_change(self, geo_information=None):
        photo = geo_information.pop('photo', False) if geo_information else False
        photo_out = geo_information.pop('photo_out', False) if geo_information else False

        attendance = super()._attendance_action_change(geo_information)
        
        if attendance:
            if photo:
                attendance.write({'check_in_photo': photo})
            if photo_out:
                attendance.write({'check_out_photo': photo_out})
        return attendance

    def attendance_manual(self, next_action, entered_pin=None, **kwargs):
        photo = kwargs.get('photo', False)
        latitude = kwargs.get('latitude', False)
        longitude = kwargs.get('longitude', False)
        
        for employee in self:
            self._check_radius(employee.company_id, latitude, longitude)
            
            # Since attendance_manual invokes _attendance_action_change under the hood (or creates the record directly)
            # We can intercept it. Let's stash the photo contextually or manually append it after the call.
            state_before = employee.attendance_state
            
            res = super(HrEmployee, employee).attendance_manual(next_action, entered_pin=entered_pin, **kwargs)
            
            # Get the created attendance record. In attendance_manual, it typically just calls _attendance_action_change
            # Let's get the last attendance id for this employee
            if photo:
                attendance = employee.last_attendance_id
                if attendance:
                    if state_before != 'checked_in':
                        attendance.write({'check_in_photo': photo})
                    else:
                        attendance.write({'check_out_photo': photo})
            
            return res
