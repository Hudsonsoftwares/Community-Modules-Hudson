from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

WEEKDAYS = [
    ('0', 'Monday'),
    ('1', 'Tuesday'),
    ('2', 'Wednesday'),
    ('3', 'Thursday'),
    ('4', 'Friday'),
    ('5', 'Saturday'),
    ('6', 'Sunday'),
]

# Standard timings loaded for a clinic that has none yet (matches the previous fixed timings)
DEFAULT_CLINIC_HOURS = (
    [(day, 'Morning', 9.0, 13.0) for day in '012345']
    + [(day, 'Afternoon', 14.0, 18.0) for day in '012345']
    + [('6', 'Sunday Hours', 10.0, 14.0)]
)


class DentalClinicHours(models.Model):
    """One working session of a clinic on a weekday (a day may have several, e.g. around lunch)."""
    _name = 'dental.clinic.hours'
    _description = 'Dental Clinic Working Hours'
    _order = 'company_id, dayofweek, hour_from'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', string='Clinic', required=True, index=True,
                                 default=lambda self: self.env.company, ondelete='cascade')
    dayofweek = fields.Selection(WEEKDAYS, string='Day', required=True, default='0')
    name = fields.Char(string='Session', default='Morning',
                       help='Shown to patients when booking, e.g. Morning, Afternoon, Evening.')
    hour_from = fields.Float(string='Opens At', required=True, default=9.0)
    hour_to = fields.Float(string='Closes At', required=True, default=13.0)

    @api.constrains('hour_from', 'hour_to')
    def _check_hours(self):
        for rec in self:
            if not (0.0 <= rec.hour_from < rec.hour_to <= 24.0):
                raise ValidationError(_("Opening time must be before closing time, within the same day (00:00-24:00)."))

    @api.constrains('company_id', 'dayofweek', 'hour_from', 'hour_to')
    def _check_overlap(self):
        for rec in self:
            overlapping = self.search_count([
                ('id', '!=', rec.id),
                ('company_id', '=', rec.company_id.id),
                ('dayofweek', '=', rec.dayofweek),
                ('hour_from', '<', rec.hour_to),
                ('hour_to', '>', rec.hour_from),
            ])
            if overlapping:
                raise ValidationError(_("Sessions on %s overlap. Adjust the timings so each session is separate.",
                                        dict(WEEKDAYS)[rec.dayofweek]))
