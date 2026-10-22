# -*- coding: utf-8 -*-
"""DST-safe timezone arithmetic for the platform.

All event timestamps in the platform are stored in UTC.  Computing the
employee's local civil date, the date a payroll cut-off would assign an
event to, is the single most error-prone operation in HR systems.

This service centralises that logic so it is correct in one place.

Odoo 20 dropped the third party timezone package from its requirements and
core reads zoneinfo everywhere, so the tz objects here come from the standard
library. The arithmetic is unchanged: a naive local time is stamped with the
zone and the zone resolves the offset for that instant, which is what makes a
23 or 25 hour DST day come out right.
"""
from datetime import UTC, datetime, date as date_cls, time as time_cls
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .base import HrService, register_service


@register_service('eh.hr.tz.service')
class TimezoneService(HrService):

    def employee_tz(self, employee):
        """Return a tzinfo for an employee, falling back to company / UTC."""
        tz_name = employee.tz or employee.company_id.partner_id.tz or 'UTC'
        try:
            return ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            return UTC

    def local_civil_date(self, employee, utc_dt: datetime) -> date_cls:
        """The civil date the event "belongs to" in the employee's locale.

        Note: an overnight shift may attribute a 02:00 local event to the
        previous civil date, which is a policy decision applied above this
        service via ``shift.overnight_anchor`` (handled in ComputeService).
        Here we return the strict locale-local date.
        """
        if utc_dt.tzinfo is None:
            utc_dt = utc_dt.replace(tzinfo=UTC)
        return utc_dt.astimezone(self.employee_tz(employee)).date()

    def day_window_utc(self, employee, civil_date: date_cls):
        """Return the (start_utc, end_utc) datetimes that bound the civil
        date for this employee.  Handles DST jumps where the day is
        23 or 25 hours long.
        """
        tz = self.employee_tz(employee)
        start_local = datetime.combine(civil_date, time_cls(0, 0), tzinfo=tz)
        end_local = datetime.combine(
            civil_date, time_cls(23, 59, 59), tzinfo=tz)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)
