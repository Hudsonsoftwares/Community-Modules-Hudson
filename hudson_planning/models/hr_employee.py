# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from datetime import UTC
from zoneinfo import ZoneInfo

from odoo import models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def _is_available_for_slot(self, slot):
        """Whether the employee works during the shift (working schedule and
        time off), used by Auto Plan. Overlapping shifts are checked on write."""
        self.ensure_one()
        calendar = self.resource_calendar_id
        if not calendar:
            return True
        start = slot.date_start.replace(tzinfo=UTC)
        end = slot.date_end.replace(tzinfo=UTC)
        # Odoo 20: the timezone is the resource's (no more on the calendar)
        tz = ZoneInfo(self.tz or self.env.user.tz or 'UTC')
        intervals = calendar._work_intervals_batch(start, end, resources_per_tz={tz: self.resource_id})[self.resource_id.id]
        worked = sum((stop - begin).total_seconds() for begin, stop, _record in intervals)
        # Working at least half of the shift.
        return worked * 2 >= (end - start).total_seconds() - slot.break_hours * 3600
