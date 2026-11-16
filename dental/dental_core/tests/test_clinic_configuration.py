from datetime import datetime, timedelta

import pytz

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'dental_clinic_configuration')
class TestClinicConfiguration(TransactionCase):
    """Per-clinic hours drive booking slots and a non-blocking outside-hours alert;
    the floor plan is per clinic and only administrators can change it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.partner_id.tz = 'Asia/Kolkata'
        cls.tz = pytz.timezone('Asia/Kolkata')
        common = {'company_id': cls.company.id, 'company_ids': [cls.company.id]}
        cls.admin = new_test_user(cls.env, login='cfg_admin', groups='base.group_user,dental_base.group_dental_admin', **common)
        cls.manager = new_test_user(cls.env, login='cfg_manager', groups='base.group_user,dental_base.group_dental_manager', **common)
        cls.doctor = cls.env['hr.employee'].create({'name': 'Dr. Hours', 'dental_role': 'dentist', 'company_id': cls.company.id})
        cls.patient = cls.env['res.partner'].create({'name': 'Hours Patient', 'is_dental_patient': True, 'phone': '9000000044'})
        # Clinic open Monday-Friday 10:00-12:00 only, 20-minute slots
        cls.company.dental_clinic_hours_ids.unlink()
        cls.env['dental.clinic.hours'].create([
            {'company_id': cls.company.id, 'dayofweek': str(d), 'name': 'Morning', 'hour_from': 10.0, 'hour_to': 12.0}
            for d in range(5)])
        cls.company.dental_slot_duration = 20
        cls.company.dental_warn_outside_hours = True

    def _next_weekday(self, weekday):
        day = datetime.now(self.tz).date() + timedelta(days=1)
        while day.weekday() != weekday:
            day += timedelta(days=1)
        return day

    def _utc(self, day, hour, minute=0):
        local = self.tz.localize(datetime.combine(day, datetime.min.time()) + timedelta(hours=hour, minutes=minute))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    def _appointment(self, day, hour):
        return self.env['dental.appointment'].create({
            'patient_id': self.patient.id, 'doctor_id': self.doctor.id, 'branch_id': self.company.id,
            'date_start': self._utc(day, hour), 'date_end': self._utc(day, hour, 30), 'state': 'confirmed'})

    def test_slots_follow_clinic_hours(self):
        monday = self._next_weekday(0)
        res = self.env['dental.appointment'].get_available_slots(
            date=monday.isoformat(), doctor_id=self.doctor.id, duration=20, branch_id=self.company.id)
        self.assertEqual([s['time'] for s in res['slots']], ['10:00', '10:20', '10:40', '11:00', '11:20', '11:40'])
        saturday = self._next_weekday(5)
        res = self.env['dental.appointment'].get_available_slots(
            date=saturday.isoformat(), doctor_id=self.doctor.id, duration=20, branch_id=self.company.id)
        self.assertFalse(res['slots'], "No session on Saturday: the clinic is closed")

    def test_outside_hours_alert_is_not_blocking(self):
        monday = self._next_weekday(0)
        inside = self._appointment(monday, 10)
        self.assertFalse(inside.outside_clinic_hours)
        late = self._appointment(monday, 19)
        self.assertTrue(late.outside_clinic_hours, "Saved anyway, but flagged")
        self.assertIn('outside', late.clinic_hours_warning)
        self.assertTrue(late.message_ids.filtered(lambda m: 'Clinic hours alert' in (m.body or '')))
        closed = self._appointment(self._next_weekday(6), 10)
        self.assertIn('closed', closed.clinic_hours_warning)
        self.company.dental_warn_outside_hours = False
        late.invalidate_recordset(['outside_clinic_hours', 'clinic_hours_warning'])
        self.assertFalse(late.outside_clinic_hours, "The alert can be switched off per clinic")

    def test_configuration_opens_selected_clinic(self):
        action = self.env['res.company'].with_user(self.admin).action_open_dental_configuration()
        self.assertEqual(action['res_id'], self.company.id)
        # Clinic administrators can edit their own clinic's configuration
        self.company.with_user(self.admin).dental_chair_count = 6
        self.assertEqual(self.company.dental_chair_count, 6)

    def test_floor_plan_admin_only_and_per_clinic(self):
        FloorPlan = self.env['dental.floor.plan']
        data = FloorPlan.with_user(self.admin).load_default_floor_plan()
        self.assertTrue(data['rooms'])
        self.assertTrue(data['can_edit'])
        palette_keys = {p['key'] for p in data['palette']}
        self.assertIn('reception', palette_keys)
        self.assertTrue({e['key'] for e in data['elements']} <= palette_keys, "Only installed modules' elements")
        # Edit: rename a room, move the elements, add an unknown element (ignored)
        rooms = [dict(r, name='Front Desk' if i == 0 else r['name']) for i, r in enumerate(data['rooms'])]
        elements = [dict(e, x=10, y=10) for e in data['elements']] + [{'id': False, 'key': 'not_a_module', 'x': 5, 'y': 5}]
        saved = FloorPlan.with_user(self.admin).save_floor_plan(rooms, elements)
        self.assertEqual(saved['rooms'][0]['name'], 'Front Desk')
        self.assertTrue(all(e['x'] == 10 for e in saved['elements']))
        self.assertNotIn('not_a_module', [e['key'] for e in saved['elements']])
        # Equipment: the standard layout places dental fixtures; they can be customised, unknown ones are ignored
        self.assertTrue(data['fixtures'])
        self.assertIn('dental_chair', {f['key'] for f in data['fixtures']})
        self.assertIn('dental_chair', {s['key'] for s in data['fixture_catalog']})
        fixtures = [dict(data['fixtures'][0], rotation=450, size=99, color='#123456', label='Chair 1', link_key='chairs'),
                    {'id': False, 'key': 'not_an_icon', 'x': 1, 'y': 1},
                    {'id': False, 'key': 'xray', 'x': 50, 'y': 50, 'color': 'red; x', 'link_key': 'bogus'}]
        elements = [dict(saved['elements'][0], svg='tooth', custom_color='#ff0000')] + saved['elements'][1:]
        saved = FloorPlan.with_user(self.admin).save_floor_plan(saved['rooms'], elements, fixtures)
        self.assertEqual(len(saved['fixtures']), 2)
        first = saved['fixtures'][0]
        self.assertEqual((first['rotation'], first['size'], first['color'], first['label'], first['link_key']),
                         (90, 25.0, '#123456', 'Chair 1', 'chairs'))
        xray = saved['fixtures'][1]
        self.assertFalse(xray['link_key'])
        self.assertNotEqual(xray['color'], 'red; x', "Invalid colours fall back to the default")
        self.assertEqual((saved['elements'][0]['svg'], saved['elements'][0]['color']), ('tooth', '#ff0000'))
        # Saving without equipment keeps it
        saved = FloorPlan.with_user(self.admin).save_floor_plan(saved['rooms'], saved['elements'])
        self.assertEqual(len(saved['fixtures']), 2)
        # Live element opens its records
        action = FloorPlan.with_user(self.admin).action_open_element('reception')
        self.assertTrue(action.get('type'))
        # Managers can view but not change the layout
        view = FloorPlan.with_user(self.manager).get_floor_plan()
        self.assertFalse(view['can_edit'])
        with self.assertRaises(AccessError):
            FloorPlan.with_user(self.manager).save_floor_plan([], [])
        # Another clinic has its own (empty) layout
        other = self.env['res.company'].create({'name': 'Second Clinic'})
        self.assertFalse(FloorPlan.with_company(other).get_floor_plan()['rooms'])

    def test_removed_tabs_hidden_from_dental_clinic_app(self):
        root = self.env.ref('dental_base.menu_dental_root')
        menus = self.env['ir.ui.menu'].with_user(self.admin).load_menus(False)
        names = [menus[c]['name'] for c in menus[root.id]['children']]
        for hidden in ('Appointments', 'Clinical', 'Pharmacy', 'Equipment & Maintenance', 'Accounting'):
            self.assertNotIn(hidden, names)
        conf = self.env.ref('dental_base.menu_dental_configuration')
        self.assertIn('Clinic Configuration', [menus[c]['name'] for c in menus[conf.id]['children']])
