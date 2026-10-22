# -*- coding: utf-8 -*-
"""The timezone service decides which civil day an event belongs to, which is
what a payroll cut-off and an attendance day are built on. Odoo 20 moved the
platform off the third party tz package onto the standard library, so the DST
edges are asserted here rather than assumed."""
from datetime import date, datetime, timedelta

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.eh_hr_core.services import locate_service


@tagged('post_install', '-at_install', 'eh_hr', 'eh_hr_platform')
class TestTimezoneService(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tz = locate_service('eh.hr.tz.service', cls.env)
        cls.employee = cls.env['hr.employee'].create({
            'name': 'EH tz probe', 'tz': 'Australia/Melbourne'})

    def test_employee_tz_is_read_from_the_employee(self):
        self.assertEqual(str(self.tz.employee_tz(self.employee)),
                         'Australia/Melbourne')

    def test_an_unknown_zone_falls_back_to_utc(self):
        # A zone name can reach the field through an import or an older
        # database; the service must answer UTC rather than raise.
        self.employee.invalidate_recordset()
        broken = self.employee.new({'tz': 'Mars/Olympus_Mons'})
        self.assertEqual(self.tz.employee_tz(broken).tzname(datetime.now()),
                         'UTC')

    def test_local_civil_date_uses_the_employee_locale(self):
        # 2024-06-30 22:00 UTC is already 1 July in Melbourne (UTC+10).
        civil = self.tz.local_civil_date(
            self.employee, datetime(2024, 6, 30, 22, 0, 0))
        self.assertEqual(civil, date(2024, 7, 1))

    def test_local_civil_date_accepts_an_aware_datetime(self):
        from datetime import UTC
        naive = self.tz.local_civil_date(
            self.employee, datetime(2024, 6, 30, 22, 0, 0))
        aware = self.tz.local_civil_date(
            self.employee, datetime(2024, 6, 30, 22, 0, 0, tzinfo=UTC))
        self.assertEqual(naive, aware,
                         'A stored naive UTC value and an aware one agree.')

    def test_day_window_is_24_hours_on_an_ordinary_day(self):
        start, end = self.tz.day_window_utc(self.employee, date(2024, 6, 12))
        self.assertEqual(start, datetime(2024, 6, 11, 14, 0,
                                         tzinfo=start.tzinfo))
        self.assertEqual((end - start), timedelta(hours=23, minutes=59,
                                                  seconds=59))

    def test_day_window_shrinks_on_the_spring_forward_day(self):
        # Melbourne moves to daylight time at 02:00 on 2024-10-06, so that
        # civil day is 23 hours long.
        start, end = self.tz.day_window_utc(self.employee, date(2024, 10, 6))
        self.assertEqual(end - start,
                         timedelta(hours=22, minutes=59, seconds=59),
                         'The spring forward day is one hour shorter.')

    def test_day_window_stretches_on_the_fall_back_day(self):
        # Melbourne leaves daylight time at 03:00 on 2024-04-07, so that
        # civil day is 25 hours long.
        start, end = self.tz.day_window_utc(self.employee, date(2024, 4, 7))
        self.assertEqual(end - start,
                         timedelta(hours=24, minutes=59, seconds=59),
                         'The fall back day is one hour longer.')

    def test_the_window_brackets_every_event_of_that_civil_day(self):
        day = date(2024, 10, 6)
        start, end = self.tz.day_window_utc(self.employee, day)
        for offset in (timedelta(minutes=1), timedelta(hours=12),
                       timedelta(hours=22, minutes=58)):
            moment = start + offset
            self.assertEqual(
                self.tz.local_civil_date(self.employee, moment), day,
                'Anything inside the window belongs to that civil day.')
        self.assertNotEqual(
            self.tz.local_civil_date(self.employee,
                                     start - timedelta(minutes=1)), day)
        self.assertNotEqual(
            self.tz.local_civil_date(self.employee, end + timedelta(seconds=2)),
            day)
