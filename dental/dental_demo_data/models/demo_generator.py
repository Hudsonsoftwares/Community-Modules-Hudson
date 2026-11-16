"""Demo dental clinic generator.

Everything is created through the real business methods (check-in, consultation, treatment
plans, invoicing, dispensing, lab workflow ...) so the records are consistent with what users
would produce. Dates are relative to the day the module is installed; timestamps that the
workflow stamps with "now" are moved back to the visit's date afterwards.

Each block runs in its own savepoint: a failure is logged and skipped instead of aborting the
whole install.
"""
import logging
import random
from datetime import date, datetime, time, timedelta

import pytz

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DEMO_PASSWORD = 'demo@1234'

# --------------------------------------------------------------------------------------------
# Static demo content
# --------------------------------------------------------------------------------------------
STAFF = [
    # key, name, login, dental_role, specialization / job, extra groups, fee
    ('ananya', 'Dr. Ananya Rao', 'dr.ananya', 'dentist', 'Orthodontist',
     ['dental_base.group_dental_dentist'], 800),
    ('vikram', 'Dr. Vikram Menon', 'dr.vikram', 'dentist', 'Endodontist',
     ['dental_base.group_dental_dentist'], 700),
    ('sara', 'Dr. Sara Thomas', 'dr.sara', 'dentist', 'Oral & Maxillofacial Surgeon',
     ['dental_base.group_dental_dentist', 'dental_second_opinion.group_dental_specialist'], 1000),
    ('reception', 'Neha Kapoor', 'reception', 'receptionist', 'Front Desk Executive',
     ['dental_base.group_dental_receptionist'], 0),
    ('labtech', 'Rahul Das', 'labtech', 'lab_tech', 'Dental Lab Technician',
     ['dental_lab.group_dental_lab_technician', 'dental_lab.group_dental_lab_user'], 0),
    ('pharmacist', 'Fatima Shaikh', 'pharmacist', 'pharmacist', 'Clinic Pharmacist',
     ['dental_pharmacy.group_dental_pharmacist'], 0),
    ('assistant1', 'Anjali Nair', False, 'assistant', 'Dental Assistant', [], 0),
    ('assistant2', 'Joseph Mathew', False, 'assistant', 'Dental Hygienist', [], 0),
]

ADMIN_GROUPS = [
    'dental_base.group_dental_admin',
    'dental_base.group_dental_dentist',
    'dental_base.group_dental_receptionist',
    'dental_lab.group_dental_lab_manager',
    'dental_pharmacy.group_dental_pharmacy_manager',
    'dental_second_opinion.group_dental_specialist',
]

FIRST_M = ['Aarav', 'Rohan', 'Arjun', 'Kabir', 'Vivaan', 'Aditya', 'Rahul', 'Siddharth', 'Karthik',
           'Nikhil', 'Imran', 'Faisal', 'George', 'Thomas', 'Manoj', 'Suresh', 'Harish', 'Varun',
           'Pranav', 'Abhishek', 'Daniel', 'Ravi']
FIRST_F = ['Priya', 'Sneha', 'Aisha', 'Meera', 'Kavya', 'Divya', 'Pooja', 'Ritika', 'Anjali',
           'Fathima', 'Lakshmi', 'Nisha', 'Shreya', 'Maria', 'Deepa', 'Swathi', 'Ishita', 'Neha',
           'Gayathri', 'Riya', 'Sana', 'Tanvi', 'Anu']
LAST = ['Sharma', 'Nair', 'Menon', 'Iyer', 'Reddy', 'Pillai', 'Khan', 'Joseph', 'Varghese',
        'Patel', 'Gupta', 'Krishnan', 'Das', 'Kumar', 'Rao', 'Thomas', 'Mehta', 'Singh', 'Bose',
        'Chandran', 'Fernandes', 'Kurian', 'Hegde']
CITIES = [('Kochi', '682016'), ('Kochi', '682020'), ('Kakkanad', '682030'), ('Aluva', '683101'),
          ('Edappally', '682024'), ('Thrippunithura', '682301'), ('Kalamassery', '683104')]
STREETS = ['MG Road', 'Panampilly Nagar', 'Kadavanthra', 'Palarivattom', 'Vyttila', 'Marine Drive',
           'Kaloor', 'Elamakkara', 'Infopark Road', 'Seaport-Airport Road']

MEDICAL = [
    (False, False, False),
    ('<p>Type 2 Diabetes mellitus (on Metformin 500 mg BD).</p>', False, '<p>Metformin 500 mg</p>'),
    ('<p>Hypertension, controlled.</p>', False, '<p>Amlodipine 5 mg OD</p>'),
    (False, '<p>Penicillin (rash)</p>', False),
    ('<p>Bronchial asthma (mild, intermittent).</p>', '<p>Aspirin / NSAIDs (wheeze)</p>', '<p>Salbutamol inhaler PRN</p>'),
    ('<p>Hypothyroidism.</p>', False, '<p>Thyroxine 50 mcg OD</p>'),
    (False, '<p>Latex</p>', False),
    ('<p>On anticoagulants after cardiac stent (2023).</p>', False, '<p>Clopidogrel 75 mg OD</p>'),
    (False, False, False),
    (False, '<p>Sulfa drugs</p>', False),
]

# Visit scenarios -----------------------------------------------------------------------------
# findings: (tooth, condition, severity, surfaces, treatment xmlid suffix, diagnosis code)
# plan: (treatment suffix, tooth, done_in_first_visit)
SCENARIOS = {
    'checkup': dict(
        complaint="Routine six-monthly check-up and cleaning.",
        findings=[('16', 'restoration', 'mild', 'O', False, False), ('36', 'restoration', 'mild', 'MO', False, False)],
        diagnoses=[('K03.6', False), ('K05.1', False)],
        plan=[('treatment_scaling', False, True)],
        exam=dict(io_calculus='mild', io_plaque='mild', perio_status='gingivitis', caries_risk='low',
                  oral_hygiene='fair', treatment_urgency='routine', recall_interval='6',
                  clinical_findings="Mild supragingival calculus in lower anteriors. Generalised marginal gingivitis."),
        rx=False, apt_type='appointment_type_routine_checkup'),
    'filling': dict(
        complaint="Food lodgement and sensitivity to sweets in lower left back tooth.",
        findings=[('36', 'caries', 'moderate', 'MO', 'treatment_dental_filling', 'K02.1'),
                  ('47', 'caries', 'mild', 'O', 'treatment_dental_filling', 'K02.0')],
        diagnoses=[('K02.1', '36'), ('K02.0', '47')],
        plan=[('treatment_dental_filling', '36', True), ('treatment_dental_filling', '47', False)],
        exam=dict(io_calculus='mild', io_plaque='moderate', caries_risk='moderate', oral_hygiene='fair',
                  treatment_urgency='soon', recall_interval='6',
                  clinical_findings="Proximal caries 36 (MO) into dentine, early occlusal caries 47."),
        rx=False, apt_type='appointment_type_comprehensive_exam'),
    'rct': dict(
        complaint="Severe throbbing pain in lower right back tooth for 3 days, worse at night.",
        findings=[('46', 'caries', 'severe', 'MOD', 'treatment_root_canal', 'K04.02')],
        diagnoses=[('K04.02', '46'), ('K04.4', '46')],
        plan=[('treatment_root_canal', '46', True), ('treatment_crown', '46', False)],
        exam=dict(io_calculus='moderate', io_plaque='moderate', caries_risk='high', oral_hygiene='fair',
                  treatment_urgency='urgent', recall_interval='3', pulse_rate=86, blood_pressure='128/84',
                  clinical_findings="Deep carious lesion 46 involving pulp. Tender on percussion. Lingering response to cold.",
                  radiographic_findings="IOPA 46: radiolucency approaching pulp, widened PDL space at mesial root."),
        rx='template_acute_infection', apt_type='appointment_type_root_canal_consultation'),
    'extraction': dict(
        complaint="Pain and swelling behind lower left last tooth, difficulty opening the mouth.",
        findings=[('38', 'impacted', 'moderate', False, 'treatment_extraction', 'K01.1')],
        diagnoses=[('K01.1', '38'), ('K05.2', '38')],
        plan=[('treatment_extraction', '38', True)],
        exam=dict(io_calculus='mild', io_plaque='mild', caries_risk='low', oral_hygiene='good',
                  treatment_urgency='soon', recall_interval='6', eo_mouth_opening=28,
                  clinical_findings="Mesioangular impacted 38 with pericoronitis.",
                  radiographic_findings="OPG: mesioangular impaction 38, close to IAN canal."),
        rx='template_post_extraction', apt_type='appointment_type_extraction_surgery'),
    'implant': dict(
        complaint="Wants to replace missing lower left tooth extracted last year.",
        findings=[('36', 'missing', False, False, 'treatment_implant', 'K08.1')],
        diagnoses=[('K08.1', '36')],
        plan=[('treatment_implant', '36', False), ('treatment_crown', '36', False)],
        exam=dict(io_calculus='none', io_plaque='mild', caries_risk='low', oral_hygiene='good',
                  treatment_urgency='routine', recall_interval='6',
                  clinical_findings="Edentulous space 36, adequate ridge width clinically.",
                  radiographic_findings="CBCT advised for bone height assessment."),
        rx=False, apt_type='appointment_type_implant_consultation'),
    'ortho': dict(
        complaint="Crooked upper front teeth, wants braces.",
        findings=[('12', 'other', 'moderate', False, False, 'K07.3'), ('22', 'other', 'moderate', False, False, 'K07.3')],
        diagnoses=[('K07.3', False), ('K07.2', False)],
        plan=[('treatment_braces', False, True)],
        exam=dict(io_calculus='none', io_plaque='mild', caries_risk='low', oral_hygiene='good',
                  treatment_urgency='routine', recall_interval='6', crowding='moderate',
                  molar_relation='class_2_div1', overjet=5.0, overbite=4.0, dentition='permanent',
                  clinical_findings="Moderate upper and lower crowding, increased overjet."),
        rx=False, apt_type='appointment_type_orthodontic_consultation'),
    'whitening': dict(
        complaint="Yellowish teeth, wants a brighter smile before wedding.",
        findings=[],
        diagnoses=[('K03.6', False)],
        plan=[('treatment_scaling', False, True), ('treatment_whitening', False, False)],
        exam=dict(io_stains='extrinsic', io_calculus='mild', caries_risk='low', oral_hygiene='good',
                  treatment_urgency='routine', recall_interval='12',
                  clinical_findings="Extrinsic tea/coffee stains, shade A3."),
        rx=False, apt_type='appointment_type_cosmetic_whitening'),
    'bridge': dict(
        complaint="Gap in lower right side, difficulty chewing.",
        findings=[('45', 'missing', False, False, 'treatment_bridge', 'K08.1'),
                  ('44', 'restoration', 'mild', 'O', False, False)],
        diagnoses=[('K08.1', '45')],
        plan=[('treatment_bridge', '44, 45, 46', False)],
        exam=dict(io_calculus='moderate', caries_risk='moderate', oral_hygiene='fair',
                  treatment_urgency='routine', recall_interval='6',
                  clinical_findings="Missing 45, abutments 44 and 46 sound."),
        rx=False, apt_type='appointment_type_comprehensive_exam'),
    'emergency': dict(
        complaint="Broke upper front tooth in a fall yesterday, sensitive to air.",
        findings=[('11', 'fracture', 'moderate', 'I', 'treatment_dental_filling', False)],
        diagnoses=[('K04.01', '11')],
        plan=[('treatment_dental_filling', '11', True), ('treatment_crown', '11', False)],
        exam=dict(io_calculus='none', caries_risk='low', oral_hygiene='good', treatment_urgency='emergency',
                  recall_interval='3', clinical_findings="Ellis class II fracture 11, no mobility."),
        rx='template_severe_pain', apt_type='appointment_type_emergency', emergency=True),
    'perio': dict(
        complaint="Bleeding gums while brushing and bad breath.",
        findings=[('31', 'other', 'moderate', False, False, 'K05.3'), ('41', 'other', 'moderate', False, False, 'K05.3')],
        diagnoses=[('K05.3', False), ('K06.0', '31')],
        plan=[('treatment_scaling', False, True), ('treatment_scaling', False, False)],
        exam=dict(io_calculus='heavy', io_plaque='heavy', io_halitosis=True, perio_status='periodontitis',
                  perio_stage='2', perio_grade='b', perio_bleeding='generalized', perio_bop_percent=42.0,
                  perio_plaque_percent=65.0, caries_risk='moderate', oral_hygiene='poor',
                  treatment_urgency='soon', recall_interval='3',
                  clinical_findings="Generalised calculus, BOP 42%, 4-5 mm pockets in lower anteriors."),
        rx='template_aphthous_ulcer', apt_type='appointment_type_periodontal_assessment'),
    'crown': dict(
        complaint="Root canal treated tooth needs a cap.",
        findings=[('26', 'root_canal', 'mild', 'MOD', 'treatment_crown', False)],
        diagnoses=[],
        plan=[('treatment_crown', '26', True)],
        exam=dict(io_calculus='mild', caries_risk='moderate', oral_hygiene='good', treatment_urgency='routine',
                  recall_interval='6', clinical_findings="RCT-treated 26 with large composite core."),
        rx=False, apt_type='appointment_type_post_op_followup'),
}
SCENARIO_WEIGHTS = [('checkup', 6), ('filling', 5), ('rct', 3), ('extraction', 2), ('implant', 1),
                    ('ortho', 1), ('whitening', 1), ('bridge', 1), ('emergency', 2), ('perio', 2), ('crown', 2)]
# Specialist bias: the right doctor gets the right kind of patient
DOCTOR_SCENARIOS = {
    'ananya': ['ortho', 'checkup', 'filling', 'whitening'],
    'vikram': ['rct', 'crown', 'filling', 'emergency'],
    'sara': ['extraction', 'implant', 'bridge', 'perio'],
}


class DentalDemoData(models.AbstractModel):
    _name = 'dental.demo.data'
    _description = 'Dental Demo Data Generator'

    @api.model
    def action_refresh_today(self):
        """Book a fresh live queue for today (for demos on later days)."""
        gen = _Generator(self.env)
        count = gen.refresh_today()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if count else 'info',
                'message': _("%s demo appointments booked for today.", count) if count
                else _("Today already has demo appointments."),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }


def post_init_hook(env):
    _Generator(env).run()


class _Generator:

    def __init__(self, env):
        self.env = env(context=dict(
            env.context,
            tracking_disable=True,
            mail_create_nolog=True,
            mail_notify_force_send=False,
            mail_auto_subscribe_no_notify=True,
            no_reset_password=True,
            lang='en_US',
        ), su=True)
        self.rng = random.Random(20261108)
        self.company = self.env.company
        self.admin = self.env.ref('base.user_admin')
        tz_name = self.admin.tz or self.company.partner_id.tz or 'UTC'
        self.tz = pytz.timezone(tz_name)
        self.today = datetime.now(self.tz).date()
        self.used_slots = set()      # (doctor_id, utc_start)
        self.staff = {}              # key -> hr.employee
        self.users = {}              # key -> res.users
        self.doctors = {}            # key -> hr.employee (dentists incl. admin)
        self.patients = self.env['res.partner']
        self.failures = []

    # ------------------------------------------------------------------ utils
    def _step(self, label, fn, *args, **kwargs):
        try:
            with self.env.cr.savepoint():
                return fn(*args, **kwargs)
        except Exception as err:  # noqa: BLE001 - demo data must never break the install
            self.failures.append('%s: %s' % (label, err))
            _logger.warning("Dental demo: %s skipped (%s)", label, err, exc_info=True)
            return None

    def _ref(self, xmlid):
        return self.env.ref(xmlid, raise_if_not_found=False)

    def _treat(self, suffix):
        return self._ref('dental_catalog.%s' % suffix)

    def _utc(self, day, hour, minute=0):
        local = self.tz.localize(datetime.combine(day, time(int(hour), int(minute))))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    def _free_slot(self, doctor, day, hours=None, duration=30):
        """A free UTC start for the doctor on that local day (30-min grid, 09:00-18:00)."""
        if hours is None:
            candidates = [h + m / 60 for h in range(9, 18) for m in (0, 30) if h != 13]
            self.rng.shuffle(candidates)
        else:
            candidates = list(hours)
        for h in candidates:
            start = self._utc(day, int(h), round((h % 1) * 60))
            if (doctor.id, start) not in self.used_slots:
                self.used_slots.add((doctor.id, start))
                return start
        return None

    def _env_as(self, user):
        return self.env(user=(user or self.admin).id, su=True)

    def _working_days(self, start, end):
        d = start
        while d <= end:
            if d.weekday() != 6:  # clinic closed on Sundays
                yield d
            d += timedelta(days=1)

    # ------------------------------------------------------------------ main
    def run(self):
        _logger.info("Dental demo: generating demo clinic for %s (tz %s)", self.today, self.tz)
        # Stock pickings notify by SMS, which lazily creates the IAP account; created inside a
        # rolled-back savepoint it would leave a stale record in cache, so create it up front.
        if 'sms.sms' in self.env and 'iap.account' in self.env:
            self.env['iap.account'].get('sms')
        self._step('company', self.setup_company)
        self._step('staff', self.create_staff)
        if not self.doctors:
            _logger.error("Dental demo: no doctors could be created, aborting")
            return
        self._step('pharmacy stock', self.create_medicine_stock)
        self._step('patients', self.create_patients)
        self._load_existing_slots()
        self.create_history()
        self.create_today()
        self._step('future appointments', self.create_future)
        self._step('waiting list', self.create_waiting_list)
        self._step('crm leads', self.create_leads)
        self._step('equipment', self.create_equipment)
        self.create_prescriptions_extra()
        self.create_lab_orders()
        self.create_ortho()
        self.create_second_opinions()
        self._step('backdate patients', self.backdate_patients)
        _logger.info("Dental demo: done. %d step(s) skipped.", len(self.failures))
        for failure in self.failures[:40]:
            _logger.info("Dental demo skipped -> %s", failure)

    def refresh_today(self):
        self._collect_existing()
        Appt = self.env['dental.appointment']
        s, e = self._utc(self.today, 0), self._utc(self.today, 23, 59)
        if Appt.search_count([('date_start', '>=', s), ('date_start', '<=', e)]) >= 5:
            return 0
        self._load_existing_slots()
        before = Appt.search_count([])
        self.create_today()
        return Appt.search_count([]) - before

    def _collect_existing(self):
        Emp = self.env['hr.employee']
        for key, _name, login, *_rest in STAFF:
            if login:
                user = self.env['res.users'].search([('login', '=', login)], limit=1)
                if user:
                    self.users[key] = user
                    emp = Emp.search([('user_id', '=', user.id)], limit=1)
                    if emp:
                        self.staff[key] = emp
                        if emp.dental_role == 'dentist':
                            self.doctors[key] = emp
        admin_emp = Emp.search([('user_id', '=', self.admin.id), ('dental_role', '=', 'dentist')], limit=1)
        if admin_emp:
            self.doctors['admin'] = admin_emp
            self.users['admin'] = self.admin
        self.patients = self.env['res.partner'].search([('is_dental_patient', '=', True)])

    def _load_existing_slots(self):
        for appt in self.env['dental.appointment'].search([('date_start', '>=', self._utc(self.today - timedelta(days=60), 0))]):
            self.used_slots.add((appt.doctor_id.id, appt.date_start))

    # ------------------------------------------------------------------ setup
    def setup_company(self):
        vals = {'dental_chair_count': max(self.company.dental_chair_count or 0, 6)}
        if 'is_dental_clinic' in self.company._fields:
            vals['is_dental_clinic'] = True
        consult = self._treat('treatment_consultation')
        if consult and not self.company.dental_consultation_product_id:
            vals['dental_consultation_product_id'] = consult.product_variant_id.id
        if not self.company.phone:
            vals['phone'] = '+91 484 400 1234'
        self.company.write(vals)

    def _groups(self, xmlids):
        return [g.id for g in (self._ref(x) for x in xmlids) if g]

    def create_staff(self):
        Users = self.env['res.users']
        Emp = self.env['hr.employee']
        dept = self.env['hr.department'].search([('name', '=', 'Dental Clinic')], limit=1) or \
            self.env['hr.department'].create({'name': 'Dental Clinic', 'company_id': self.company.id})

        # The Administrator is a dentist: the Dentist Workspace shows his own day
        self.admin.write({'group_ids': [Command.link(g) for g in self._groups(ADMIN_GROUPS)]})
        admin_emp = Emp.search([('user_id', '=', self.admin.id), ('company_id', '=', self.company.id)], limit=1)
        admin_vals = {
            'dental_role': 'dentist', 'specialization': 'General & Cosmetic Dentistry',
            'registration_number': 'KDC-2011-0457', 'consultation_fee': 600, 'job_title': 'Chief Dental Surgeon',
            'department_id': dept.id,
        }
        if admin_emp:
            admin_emp.write(admin_vals)
        else:
            admin_emp = Emp.create(dict(admin_vals, name=self.admin.name, user_id=self.admin.id,
                                        company_id=self.company.id, work_email=self.admin.email))
        self.doctors['admin'] = admin_emp
        self.staff['admin'] = admin_emp
        self.users['admin'] = self.admin

        for i, (key, name, login, role, spec, groups, fee) in enumerate(STAFF):
            user = False
            if login:
                user = Users.with_context(active_test=False).search([('login', '=', login)], limit=1)
                if not user:
                    user = Users.create({
                        'name': name, 'login': login, 'password': DEMO_PASSWORD,
                        'email': '%s@demo-dental.example.com' % login.replace('.', ''),
                        'tz': self.tz.zone, 'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
                        'group_ids': [Command.set([self.env.ref('base.group_user').id] + self._groups(groups))],
                    })
                self.users[key] = user
            emp = Emp.search([('user_id', '=', user.id)], limit=1) if user else Emp.search([('name', '=', name)], limit=1)
            vals = {
                'name': name, 'dental_role': role, 'job_title': spec, 'department_id': dept.id,
                'company_id': self.company.id, 'work_phone': '+91 98470 %05d' % (10101 + i * 1111),
                'work_email': user.email if user else False, 'user_id': user.id if user else False,
            }
            if role == 'dentist':
                vals.update(specialization=spec, consultation_fee=fee, registration_number='KDC-%d-%04d' % (2012 + i, 1200 + i * 37))
            emp = emp.write(vals) and emp if emp else Emp.create(vals)
            self.staff[key] = emp
            if role == 'dentist':
                self.doctors[key] = emp
        if 'assigned_dentist_id' in Emp._fields:
            self.staff['assistant1'].assigned_dentist_id = self.doctors['admin'].id
            self.staff['assistant2'].assigned_dentist_id = self.doctors['vikram'].id

    def create_medicine_stock(self):
        meds = self.env['product.product'].search([('is_medicine', '=', True)])
        location = self.env['stock.warehouse'].search([('company_id', '=', self.company.id)], limit=1).lot_stock_id
        if not location:
            return
        Lot = self.env['stock.lot']
        Quant = self.env['stock.quant']
        for idx, med in enumerate(meds):
            if Quant.search_count([('product_id', '=', med.id), ('location_id', '=', location.id), ('quantity', '>', 0)]):
                continue
            batches = [('B%s%02d' % (self.today.strftime('%y%m'), idx), 540, 300)]
            if idx % 3 == 0:
                batches.append(('N%s%02d' % (self.today.strftime('%y%m'), idx), 45, 20))  # near expiry -> alerts
            for name, days, qty in batches:
                lot_vals = {'name': name, 'product_id': med.id, 'company_id': self.company.id}
                if 'expiry_date' in Lot._fields:
                    lot_vals['expiry_date'] = self.today + timedelta(days=days)
                lot = Lot.create(lot_vals) if med.tracking != 'none' else Lot
                Quant.with_context(inventory_mode=True).create({
                    'product_id': med.id, 'location_id': location.id, 'lot_id': lot.id or False,
                    'inventory_quantity': qty,
                }).action_apply_inventory()

    def create_patients(self):
        Partner = self.env['res.partner']
        existing = Partner.search_count([('is_dental_patient', '=', True)])
        rng = self.rng
        vals_list = []
        used = set()
        target = 45
        while len(vals_list) < target:
            female = rng.random() < 0.52
            first = rng.choice(FIRST_F if female else FIRST_M)
            last = rng.choice(LAST)
            name = '%s %s' % (first, last)
            if name in used:
                continue
            used.add(name)
            n = len(vals_list)
            age = rng.choice([8, 11, 14, 17, 22, 26, 29, 31, 34, 38, 42, 45, 51, 56, 62, 68, 73])
            dob = self.today - timedelta(days=age * 365 + rng.randint(0, 360))
            city, zip_code = rng.choice(CITIES)
            med, allergy, meds = MEDICAL[n % len(MEDICAL)]
            vals = {
                'name': name, 'is_dental_patient': True, 'customer_rank': 1,
                'phone': '+91 9%d' % (846000000 + n * 7919 + existing),
                'email': ('%s.%s%d@example.com' % (first, last, n)).lower() if n % 4 else False,
                'street': '%d, %s' % (rng.randint(3, 220), rng.choice(STREETS)), 'city': city, 'zip': zip_code,
                'country_id': self.env.ref('base.in').id,
                'date_of_birth': dob, 'gender': 'female' if female else 'male',
                'blood_group': rng.choice(['A+', 'B+', 'O+', 'O+', 'AB+', 'A-', 'B-', 'O-']),
                'emergency_contact': '+91 9%d' % (747000000 + n * 3571),
                'oral_hygiene': rng.choice(['good', 'good', 'fair', 'poor']),
                'smoking_tobacco_history': rng.choice(['none', 'none', 'none', 'occasional', 'frequent']),
                'brushing_frequency': rng.choice(['twice', 'twice', 'once', 'once', 'rarely']),
                'last_dental_visit': self.today - timedelta(days=rng.randint(200, 900)),
                'medical_history': med or '<p>No significant medical history.</p>',
                'current_medications': meds or False,
                'allergies': allergy or False,
                'allergy_status': 'known' if allergy else rng.choice(['none', 'none', 'unknown']),
                'dental_history': rng.choice([
                    '<p>Previous fillings in molars.</p>', '<p>Extraction of 18 and 28 in 2019.</p>',
                    '<p>Regular cleanings, no major treatment.</p>', '<p>RCT on 16 five years ago.</p>',
                    '<p>Braces as a teenager.</p>', False]),
            }
            if age < 16:
                vals['clinical_alerts'] = '<p>Minor - guardian consent required.</p>'
            if 'Clopidogrel' in (meds or ''):
                vals['clinical_alerts'] = '<p>On antiplatelet therapy - check bleeding risk before surgery.</p>'
            vals_list.append(vals)
        self.patients = Partner.create(vals_list)

    def backdate_patients(self):
        """Patients registered over the last year; three of them today (reception KPI)."""
        recent = self.patients[-3:]
        for p in self.patients - recent:
            created = datetime.combine(self.today - timedelta(days=self.rng.randint(50, 400)), time(5, 0))
            self.env.cr.execute("UPDATE res_partner SET create_date = %s WHERE id = %s", (created, p.id))
        self.patients.invalidate_recordset(['create_date'])

    # ------------------------------------------------------------------ appointments
    def _pick_doctor(self):
        keys = list(self.doctors)
        weights = [4 if k == 'admin' else 2 for k in keys]
        return self.rng.choices(keys, weights=weights)[0]

    def _pick_scenario(self, doc_key):
        if doc_key in DOCTOR_SCENARIOS and self.rng.random() < 0.7:
            return self.rng.choice(DOCTOR_SCENARIOS[doc_key])
        names, weights = zip(*SCENARIO_WEIGHTS)
        return self.rng.choices(names, weights=weights)[0]

    def _create_appt(self, patient, doc_key, start, scenario=None, state='confirmed', duration=30, **extra):
        doctor = self.doctors[doc_key]
        scen = SCENARIOS.get(scenario) if scenario else None
        apt_type = self._ref('dental_appointment.%s' % scen['apt_type']) if scen else False
        treatment = self._treat(scen['plan'][0][0]) if scen and scen['plan'] else False
        vals = {
            'patient_id': patient.id, 'doctor_id': doctor.id, 'branch_id': self.company.id,
            'date_start': start, 'date_end': start + timedelta(minutes=duration),
            'reason': scen['complaint'] if scen else extra.pop('reason', 'Consultation'),
            'appointment_type_id': apt_type.id if apt_type else False,
            'treatment_id': treatment.id if treatment else False,
            'is_emergency': bool(scen and scen.get('emergency')),
            'state': 'pending' if state == 'pending' else 'confirmed',
        }
        vals.update(extra)
        user = self.users.get(doc_key) or self.admin
        reception = self.users.get('reception') or self.admin
        return self.env['dental.appointment'].with_env(self._env_as(reception)).create(vals).with_env(self._env_as(user))

    # ------------------------------------------------------------------ clinical flow
    def _clinical_visit(self, appt, scenario, visit_dt, complete=True, prescribe=True):
        """Check in, consult, examine, plan, treat, complete and bill one visit."""
        doc_user = appt.env.user
        appt.action_check_in()
        appt.action_start_consultation()
        case = appt.case_id
        if not case:
            raise UserError('no case created')
        continued = case.appointment_id != appt
        scen = SCENARIOS[scenario]
        Exam = self.env['dental.clinical.examination'].with_env(appt.env)
        exam = Exam.search([('appointment_id', '=', appt.id)], limit=1)
        if not exam:
            exam = Exam.create({'patient_id': appt.patient_id.id, 'case_id': case.id, 'appointment_id': appt.id,
                                'doctor_id': appt.doctor_id.id})
        if not case.chief_complaint:
            case.chief_complaint = scen['complaint']

        if continued:
            line = case.treatment_plan_ids.line_ids.filtered(
                lambda l: l.state not in ('completed', 'cancelled') and l.acceptance == 'accepted'
                and l.plan_id.state not in ('completed', 'cancelled'))[:1]
            exam.write({'chief_complaint': 'Review / next treatment visit', 'clinical_findings': 'Healing satisfactory. Proceeding with planned treatment.',
                        'pulse_rate': self.rng.randint(68, 88), 'blood_pressure': self.rng.choice(['118/76', '124/80', '130/84'])})
            if line:
                line.action_mark_visit_done()
        else:
            exam_vals = dict(scen['exam'])
            exam_vals.setdefault('pulse_rate', self.rng.randint(66, 90))
            exam_vals.setdefault('blood_pressure', self.rng.choice(['116/74', '122/80', '128/82', '136/88']))
            exam_vals.update(chief_complaint=scen['complaint'], temperature=round(self.rng.uniform(97.8, 98.9), 1),
                             oxygen_saturation=float(self.rng.randint(96, 99)))
            exam.write({k: v for k, v in exam_vals.items() if k in exam._fields})
            self._findings(appt, case, exam, scen)
            plan = self._plan(appt, case, scen)
            if plan:
                accept = scenario not in ('implant', 'bridge') or self.rng.random() < 0.5
                plan.action_propose()
                if accept:
                    plan.action_accept()
                    for (suffix, tooth, do_now), line in zip(scen['plan'], plan.line_ids.sorted('id')):
                        if do_now:
                            line.action_mark_visit_done()
        if prescribe and scen.get('rx') and not continued:
            self._step('prescription %s' % appt.name, self._prescribe, appt, case, scen['rx'])
        if not complete:
            return case
        case.action_complete_consultation()
        self._fix_times(appt, case, exam, visit_dt)
        return case

    def _findings(self, appt, case, exam, scen):
        Finding = self.env['dental.tooth.finding'].with_env(appt.env)
        Diag = self.env['dental.diagnosis']
        PDiag = self.env['dental.patient.diagnosis'].with_env(appt.env)
        for tooth, cond, sev, surf, treat, code in scen['findings']:
            diag = Diag.search([('code', '=', code)], limit=1) if code else Diag
            treatment = self._treat(treat) if treat else False
            vals = {'patient_id': appt.patient_id.id, 'case_id': case.id, 'examination_id': exam.id,
                    'doctor_id': appt.doctor_id.id, 'tooth_number': tooth, 'condition': cond,
                    'severity': sev or False, 'surfaces': surf or False,
                    'clinical_action': 'treat' if treatment else 'monitor',
                    'treatment_id': treatment.id if treatment else False,
                    'diagnosis_id': diag.id or False}
            Finding.create(vals)
        for code, tooth in scen['diagnoses']:
            diag = Diag.search([('code', '=', code)], limit=1)
            if diag:
                PDiag.create({'patient_id': appt.patient_id.id, 'case_id': case.id, 'examination_id': exam.id,
                              'doctor_id': appt.doctor_id.id, 'diagnosis_id': diag.id, 'tooth_reference': tooth or False,
                              'status': 'confirmed'})

    def _plan(self, appt, case, scen):
        if not scen['plan']:
            return False
        Stage = self.env['dental.treatment.stage']
        lines = []
        for suffix, tooth, _do in scen['plan']:
            treatment = self._treat(suffix)
            if not treatment:
                continue
            stage = Stage.search([('treatment_id', '=', treatment.id)], order='sequence, id', limit=1) or \
                Stage.search([('treatment_id', '=', False)], order='sequence, id', limit=1)
            lines.append(Command.create({
                'treatment_id': treatment.id, 'tooth_reference': tooth or False, 'quantity': 1,
                'unit_price': treatment.list_price, 'description': treatment.name,
                'number_of_visits': treatment.number_of_visits or 1, 'visit_interval': treatment.visit_interval,
                'stage_id': stage.id or False,
            }))
        if not lines:
            return False
        return self.env['dental.treatment.plan'].with_env(appt.env).create({
            'patient_id': appt.patient_id.id, 'case_id': case.id, 'doctor_id': appt.doctor_id.id,
            'appointment_id': appt.id, 'line_ids': lines,
            'notes': 'Treatment options, costs and alternatives explained to the patient.',
        })

    def _fix_times(self, appt, case, exam, visit_dt):
        """Workflow stamps 'now'; move the visit back to when it happened."""
        check_in = visit_dt - timedelta(minutes=self.rng.randint(5, 20))
        called = visit_dt + timedelta(minutes=self.rng.randint(0, 10))
        done = called + timedelta(minutes=self.rng.randint(20, 45))
        appt.write({'check_in_time': check_in, 'called_time': called})
        local_day = pytz.utc.localize(visit_dt).astimezone(self.tz).date()
        case_vals = {'completion_time': done}
        if case.appointment_id == appt:
            case_vals['case_date'] = local_day
        case.write(case_vals)
        exam.write({'examination_date': called, 'completed_date': done})
        sessions = self.env['dental.treatment.session'].search([('appointment_id', '=', appt.id)])
        sessions.write({'session_date': called})
        plans = self.env['dental.treatment.plan'].search([('appointment_id', '=', appt.id)])
        plans.filtered(lambda p: p.accepted_date).write({'accepted_date': done})
        plans.write({'plan_date': local_day})
        self.env['dental.tooth.finding'].search([('examination_id', '=', exam.id)]).write({'finding_date': called})
        self.env['dental.patient.diagnosis'].search([('examination_id', '=', exam.id)]).write({'date': local_day})
        # Follow-ups / recalls were scheduled relative to today
        shift = (local_day - self.today)
        if shift:
            for fu in self.env['dental.follow.up'].search([('appointment_id', '=', appt.id)]):
                fu.date = fu.date + shift
            for rc in self.env['dental.recall'].search([('last_appointment_id', '=', appt.id)]):
                rc.due_date = rc.due_date + shift
            for rx in self.env['dental.prescription'].search([('appointment_id', '=', appt.id)]):
                rx.prescription_date = local_day
        appt.patient_id.sudo().last_dental_visit = local_day

    def _bill(self, case, visit_day, pay=True):
        invoices = case.invoice_ids if 'invoice_ids' in case._fields else self.env['account.move']
        draft = invoices.filtered(lambda m: m.state == 'draft')
        for inv in draft:
            inv.write({'invoice_date': visit_day, 'date': visit_day})
            inv.action_post()
            if pay and inv.amount_residual > 0:
                method = self.rng.choice(self.env['account.journal'].search(
                    [('type', 'in', ('bank', 'cash')), ('company_id', '=', self.company.id)]).ids or [False])
                ctx = {'active_model': 'account.move', 'active_ids': inv.ids}
                vals = {'payment_date': visit_day}
                if method:
                    vals['journal_id'] = method
                self.env['account.payment.register'].with_context(**ctx).create(vals)._create_payments()

    def _prescribe(self, appt, case, template_suffix):
        template = self._ref('dental_pharmacy.%s' % template_suffix) or \
            self.env['dental.prescription.template'].search([], limit=1)
        Rx = self.env['dental.prescription'].with_env(appt.env)
        lines = []
        for tl in template.line_ids if template else []:
            vals = {'medicine_id': tl.medicine_id.id}
            for f in ('dose', 'frequency', 'duration', 'route', 'quantity', 'instructions'):
                if f in tl._fields and tl[f]:
                    vals[f] = tl[f]
            lines.append(Command.create(vals))
        if not lines:
            meds = self.env['product.product'].search([('is_medicine', '=', True)], limit=2)
            lines = [Command.create({'medicine_id': m.id, 'dose': '1 tablet', 'frequency': 'bid', 'duration': 5,
                                     'route': 'oral', 'quantity': 10}) for m in meds]
        employee = self.env['hr.employee'].browse(appt.doctor_id.id)
        rx = Rx.create({'patient_id': appt.patient_id.id, 'case_id': case.id, 'appointment_id': appt.id,
                        'dentist_id': employee.id, 'template_id': template.id if template else False,
                        'diagnosis': case.chief_complaint and case.chief_complaint[:80],
                        'line_ids': lines})
        rx.action_confirm()
        return rx

    def _dispense(self, rx):
        pharmacist = self.users.get('pharmacist') or self.admin
        rx = rx.with_env(self._env_as(pharmacist))
        rx.action_dispense()
        dispense = self.env['dental.pharmacy.dispense'].with_env(rx.env).search(
            [('prescription_id', '=', rx.id), ('state', '=', 'draft')], limit=1)
        for line in dispense.line_ids:
            if line.medicine_id.tracking == 'none':
                continue
            on_hand = sum(self.env['stock.quant'].search([('lot_id', '=', line.lot_id.id),
                                                          ('location_id.usage', '=', 'internal')]).mapped('quantity')) if line.lot_id else 0
            if on_hand < line.qty_to_dispense:
                quant = self.env['stock.quant'].search([
                    ('product_id', '=', line.medicine_id.id), ('location_id.usage', '=', 'internal'),
                    ('lot_id', '!=', False), ('quantity', '>=', line.qty_to_dispense)], order='quantity desc', limit=1)
                if quant:
                    line.lot_id = quant.lot_id.id
        dispense.action_dispense()
        return dispense

    # ------------------------------------------------------------------ history
    def create_history(self):
        """Six weeks of visits. Returning patients continue their open cases."""
        start = self.today - timedelta(days=42)
        days = list(self._working_days(start, self.today - timedelta(days=1)))
        patient_cycle = list(self.patients[:-3])  # the last three registered today
        self.rng.shuffle(patient_cycle)
        patient_case = {}
        count = 0
        for day in days:
            for _i in range(self.rng.randint(2, 4)):
                if not patient_cycle:
                    break
                # 70% new patients until everybody has been seen once, then returning ones
                if count < len(self.patients) - 3 and self.rng.random() < 0.8:
                    patient = patient_cycle[count % len(patient_cycle)]
                else:
                    patient = self.rng.choice(patient_cycle)
                count += 1
                if patient.id in patient_case:
                    doc_key, scenario = patient_case[patient.id]
                else:
                    doc_key = self._pick_doctor()
                    scenario = self._pick_scenario(doc_key)
                start_dt = self._free_slot(self.doctors[doc_key], day)
                if not start_dt:
                    continue
                roll = self.rng.random()
                if roll < 0.06:
                    self._step('no-show', lambda: self._create_appt(patient, doc_key, start_dt, scenario).action_no_show())
                    continue
                if roll < 0.12:
                    self._step('cancelled', lambda: self._create_appt(patient, doc_key, start_dt, scenario).action_cancel())
                    continue
                res = self._step('visit %s %s' % (day, patient.name), self._history_visit, patient, doc_key, scenario, start_dt, day)
                if res:
                    patient_case[patient.id] = (doc_key, scenario)

    def _history_visit(self, patient, doc_key, scenario, start_dt, day):
        appt = self._create_appt(patient, doc_key, start_dt, scenario)
        case = self._clinical_visit(appt, scenario, start_dt)
        recent = (self.today - day).days <= 2
        self._bill(case, day, pay=not recent or self.rng.random() < 0.5)
        if self.rng.random() < 0.85:
            for rx in self.env['dental.prescription'].search([('appointment_id', '=', appt.id), ('state', '=', 'confirmed')]):
                self._step('dispense %s' % rx.name, self._dispense, rx)
        return case

    # ------------------------------------------------------------------ today
    def create_today(self):
        """A live day for every dentist: done, in the chair, waiting, still to come."""
        Appt = self.env['dental.appointment']
        returning = self.patients[:-3]
        new_today = self.patients[-3:]
        pool = list(returning)
        self.rng.shuffle(pool)
        pool = list(new_today) + pool
        plan = {
            # doctor: list of (local hour, target state)
            'admin': [(9, 'completed'), (9.5, 'completed'), (10, 'completed'), (10.5, 'in_consultation'),
                      (11, 'checked_in'), (11.5, 'checked_in'), (12, 'checked_in'), (14, 'confirmed'),
                      (14.5, 'confirmed'), (15, 'confirmed'), (16, 'pending'), (16.5, 'no_show')],
            'ananya': [(9, 'completed'), (10, 'completed'), (11, 'in_consultation'), (11.5, 'checked_in'),
                       (15, 'confirmed'), (16, 'confirmed'), (17, 'cancelled')],
            'vikram': [(9.5, 'completed'), (10.5, 'in_consultation'), (11.5, 'checked_in'), (12, 'checked_in'),
                       (14.5, 'confirmed'), (15.5, 'pending')],
            'sara': [(9, 'completed'), (10, 'checked_in'), (14, 'confirmed'), (15, 'confirmed'), (16, 'confirmed')],
        }
        idx = 0
        for doc_key, slots in plan.items():
            if doc_key not in self.doctors:
                continue
            doctor = self.doctors[doc_key]
            for hour, state in slots:
                start = self._free_slot(doctor, self.today, hours=[hour, hour + 0.5, hour + 1, 17.5])
                if not start or not pool:
                    continue
                patient = pool[idx % len(pool)]
                idx += 1
                scenario = self._pick_scenario(doc_key)
                if doc_key == 'admin' and hour == 11:
                    scenario = 'emergency'
                self._step('today %s %s' % (doc_key, state), self._today_visit, patient, doc_key, scenario, start, state)
        return Appt

    def _today_visit(self, patient, doc_key, scenario, start, state):
        appt = self._create_appt(patient, doc_key, start, scenario, state=state)
        now = fields.Datetime.now()
        if state == 'completed':
            case = self._clinical_visit(appt, scenario, start)
            # Today's bills stay as drafts for the front desk (billing queue)
            return case
        if state == 'in_consultation':
            self._clinical_visit(appt, scenario, start, complete=False)
            appt.write({'check_in_time': min(now, start) - timedelta(minutes=15), 'called_time': min(now, start)})
            return appt
        if state == 'checked_in':
            appt.action_check_in()
            appt.write({'check_in_time': min(now, start) - timedelta(minutes=self.rng.randint(5, 25))})
            return appt
        if state == 'no_show':
            appt.action_no_show()
        elif state == 'cancelled':
            appt.action_cancel()
        return appt

    # ------------------------------------------------------------------ future
    def create_future(self):
        """Three weeks of bookings, including the follow-ups that were scheduled."""
        FollowUp = self.env['dental.follow.up']
        follow_ups = FollowUp.search([('state', '=', 'pending'), ('date', '>', self.today)], order='date')
        booked = 0
        for fu in follow_ups[: int(len(follow_ups) * 0.6)]:
            doc_key = next((k for k, d in self.doctors.items() if d.id == fu.doctor_id.id), self._pick_doctor())
            day = fu.date if fu.date.weekday() != 6 else fu.date + timedelta(days=1)
            start = self._free_slot(self.doctors[doc_key], day)
            if not start:
                continue
            res = self._step('book follow-up', lambda: self.env['dental.appointment'].with_context(dental_follow_up_id=fu.id).create({
                'patient_id': fu.patient_id.id, 'doctor_id': self.doctors[doc_key].id, 'branch_id': self.company.id,
                'date_start': start, 'date_end': start + timedelta(minutes=30), 'state': 'confirmed',
                'reason': fu.reason or 'Follow-up visit', 'treatment_id': fu.treatment_id.id or False,
                'appointment_type_id': self._ref('dental_appointment.appointment_type_post_op_followup').id,
            }))
            booked += bool(res)
        for day in self._working_days(self.today + timedelta(days=1), self.today + timedelta(days=21)):
            for _i in range(self.rng.randint(2, 4)):
                doc_key = self._pick_doctor()
                start = self._free_slot(self.doctors[doc_key], day)
                if start:
                    state = 'pending' if self.rng.random() < 0.25 else 'confirmed'
                    self._step('future visit', self._create_appt, self.rng.choice(self.patients), doc_key, start,
                               self._pick_scenario(doc_key), state=state)
        _logger.info("Dental demo: %d follow-ups booked", booked)

    # ------------------------------------------------------------------ front desk extras
    def create_waiting_list(self):
        WL = self.env['dental.waiting.list']
        prios = ['normal', 'normal', 'high', 'emergency', 'normal', 'high', 'normal', 'normal']
        for i, patient in enumerate(self.rng.sample(list(self.patients), 8)):
            doc_key = self._pick_doctor()
            scen = SCENARIOS[self._pick_scenario(doc_key)]
            frm = self._utc(self.today + timedelta(days=i % 5 + 1), 9)
            WL.create({
                'patient_id': patient.id, 'doctor_id': self.doctors[doc_key].id,
                'treatment_id': self._treat(scen['plan'][0][0]).id if scen['plan'] else False,
                'priority': prios[i], 'date_from': frm, 'date_to': frm + timedelta(days=3, hours=8),
                'state': 'waiting' if i < 6 else 'assigned',
                'notes': 'Prefers %s slots. %s' % (self.rng.choice(['morning', 'evening', 'weekend']), scen['complaint']),
            })

    def create_leads(self):
        Lead = self.env['crm.lead']
        enquiries = [
            ('Braces enquiry for teenage son', 'treatment_braces', 'instagram', 'new'),
            ('Implant cost for missing molar', 'treatment_implant', 'google', 'contacted'),
            ('Teeth whitening before wedding', 'treatment_whitening', 'facebook', 'follow_up'),
            ('Wisdom tooth pain - wants extraction', 'treatment_extraction', 'phone', 'appointment_scheduled'),
            ('Root canal second opinion', 'treatment_root_canal', 'referral', 'contacted'),
            ('Full mouth cleaning for family of 4', 'treatment_scaling', 'website', 'new'),
            ('Clear aligner consultation', 'treatment_braces', 'website', 'follow_up'),
            ('Crown replacement - broken cap', 'treatment_crown', 'walk_in', 'appointment_completed'),
            ('Bridge vs implant comparison', 'treatment_bridge', 'google', 'new'),
            ('Kids dental check-up (school camp)', 'treatment_consultation', 'other', 'contacted'),
            ('Smile makeover package enquiry', 'treatment_whitening', 'instagram', 'new'),
            ('Bleeding gums - wants treatment', 'treatment_scaling', 'phone', 'cancelled'),
        ]
        stages = self.env['crm.stage'].search([], order='sequence')
        for i, (title, treat, src, status) in enumerate(enquiries):
            first = self.rng.choice(FIRST_F + FIRST_M)
            last = self.rng.choice(LAST)
            doc_key = self._pick_doctor()
            vals = {
                'name': title, 'type': 'opportunity', 'contact_name': '%s %s' % (first, last),
                'phone': '+91 9%d' % (812000000 + i * 4111), 'email_from': '%s.%s@example.net' % (first.lower(), last.lower()),
                'treatment_id': self._treat(treat).id if self._treat(treat) else False,
                'preferred_doctor_id': self.doctors[doc_key].id,
                'preferred_date': self._utc(self.today + timedelta(days=i % 9 + 1), 10 + i % 6),
                'enquiry_date': self._utc(self.today - timedelta(days=i * 2), 11),
                'source_type': src, 'conversion_status': status,
                'expected_revenue': (self._treat(treat).list_price if self._treat(treat) else 100) * self.rng.choice([1, 1, 2]),
                'user_id': (self.users.get('reception') or self.admin).id,
                'stage_id': stages[min(i % 4, len(stages) - 1)].id if stages else False,
            }
            if src == 'referral':
                vals['referring_patient_id'] = self.patients[0].id
            Lead.create({k: v for k, v in vals.items() if k in Lead._fields})

    def create_equipment(self):
        Equip = self.env['maintenance.equipment']
        cat = lambda x: self._ref('dental_core.equipment_category_%s' % x)  # noqa: E731
        items = [
            ('Dental Chair - Operatory 1', 'dental_chairs', 'operational', 'A-dec 500', 180, 400),
            ('Dental Chair - Operatory 2', 'dental_chairs', 'operational', 'A-dec 500', 180, 380),
            ('Dental Chair - Operatory 3', 'dental_chairs', 'needs_maintenance', 'Sirona Intego', 180, 700),
            ('Dental Chair - Operatory 4', 'dental_chairs', 'operational', 'Sirona Intego', 180, 120),
            ('Autoclave Class B 23L', 'autoclaves', 'operational', 'W&H Lisa', 90, 200),
            ('OPG / CBCT Unit', 'imaging', 'under_repair', 'Planmeca ProMax 3D', 365, 900),
            ('Intraoral X-ray Unit', 'imaging', 'operational', 'Carestream CS 2200', 365, 500),
            ('Oil-free Air Compressor', 'compressors', 'operational', 'Durr Tornado 2', 120, 800),
            ('Ultrasonic Scaler', 'scalers', 'operational', 'EMS Piezon', 180, 60),
            ('Intraoral Scanner', 'other', 'operational', 'iTero Element 5D', 365, 30),
        ]
        technician = self.users.get('labtech') or self.admin
        equipment = Equip
        for name, c, cond, model, freq, age_days in items:
            category = cat(c)
            vals = {
                'name': name, 'category_id': category.id if category else False, 'model': model,
                'serial_no': 'SN-%s-%04d' % (c[:3].upper(), self.rng.randint(1000, 9999)),
                'equipment_condition': cond, 'preventive_frequency_days': freq,
                'last_maintenance_date': self.today - timedelta(days=self.rng.randint(10, freq + 20)),
                'effective_date': self.today - timedelta(days=age_days),
                'warranty_date': self.today + timedelta(days=self.rng.choice([-60, 20, 200, 500])),
                'branch_id': self.company.id, 'company_id': self.company.id, 'technician_user_id': technician.id,
            }
            equipment |= Equip.create({k: v for k, v in vals.items() if k in Equip._fields})
        Req = self.env['maintenance.request']
        stage_new = self.env['maintenance.stage'].search([], order='sequence', limit=1)
        done_stage = self.env['maintenance.stage'].search([('name', 'in', ('Repaired', 'Closed'))], limit=1)
        reqs = [
            ('Chair 3 - hydraulic leak', equipment[2], 'corrective', stage_new, 2),
            ('CBCT - sensor calibration error', equipment[5], 'corrective', stage_new, 3),
            ('Autoclave quarterly validation', equipment[4], 'preventive', stage_new, 1),
            ('Compressor filter change', equipment[7], 'preventive', done_stage, 1),
            ('Scaler tip replacement', equipment[8], 'corrective', done_stage, 0),
        ]
        for name, eq, mtype, stage, prio in reqs:
            vals = {'name': name, 'equipment_id': eq.id, 'maintenance_type': mtype, 'priority': str(min(prio, 3)),
                    'stage_id': stage.id if stage else False, 'user_id': technician.id,
                    'schedule_date': self._utc(self.today + timedelta(days=self.rng.randint(-5, 10)), 15)}
            Req.create({k: v for k, v in vals.items() if k in Req._fields})

    # ------------------------------------------------------------------ pharmacy extras
    def create_prescriptions_extra(self):
        """Prescriptions waiting at the pharmacy, issued to patients and OTC sales."""
        cases = self.env['dental.case'].search([], order='id desc', limit=12)
        for i, case in enumerate(cases[:6]):
            appt = case.appointment_id
            if not appt:
                continue
            user = next((self.users[k] for k, d in self.doctors.items() if d.id == case.doctor_id.id), self.admin)
            appt = appt.with_env(self._env_as(user))
            tmpl = ['template_acute_infection', 'template_post_extraction', 'template_severe_pain', 'template_aphthous_ulcer'][i % 4]
            rx = self._step('extra rx', self._prescribe, appt, case, tmpl)
            if rx and i % 3 == 2:
                self._step('issue rx', lambda r=rx: r.with_env(self._env_as(self.users.get('reception'))).action_issue_to_patient())
            elif rx and i % 3 == 1:
                self._step('draft rx', lambda r=rx: r.action_draft())

    # ------------------------------------------------------------------ lab
    def create_lab_orders(self):
        lines = self.env['dental.treatment.plan.line'].search([
            ('treatment_id', 'in', [t.id for t in (self._treat('treatment_crown'), self._treat('treatment_bridge'),
                                                    self._treat('treatment_implant'), self._treat('treatment_braces')) if t]),
            ('acceptance', '=', 'accepted')], order='id')
        external = self.env['res.partner'].search([('name', '=', 'SmileCraft Dental Laboratory')], limit=1) or \
            self.env['res.partner'].create({'name': 'SmileCraft Dental Laboratory', 'is_company': True, 'supplier_rank': 1,
                                            'phone': '+91 484 255 7788', 'city': 'Kochi'})
        targets = ['closed', 'closed', 'dentist_accepted', 'received_clinic', 'dispatched', 'finished',
                   'qc_pending', 'in_production', 'in_production', 'submitted', 'draft', 'rework', 'cancelled']
        type_map = {'treatment_crown': 'crown', 'treatment_bridge': 'bridge', 'treatment_implant': 'implant_crown',
                    'treatment_braces': 'retainer'}
        material_map = {'crown': 'zirconia_ml', 'bridge': 'pfm', 'implant_crown': 'zirconia_mono', 'retainer': 'acrylic'}
        for i, pl in enumerate(lines[: len(targets)]):
            self._step('lab order %d' % i, self._lab_order, pl, targets[i], external if i % 4 == 3 else False, type_map, material_map)

    def _lab_order(self, pl, target, external, type_map, material_map):
        case = pl.plan_id.case_id
        if not case:
            return
        doctor_user = next((self.users[k] for k, d in self.doctors.items() if d.id == pl.plan_id.doctor_id.id), self.admin)
        denv = self._env_as(doctor_user)
        suffix = next((s for s, t in type_map.items() if self._treat(s) == pl.treatment_id), 'treatment_crown')
        rtype = type_map[suffix]
        tooth = (pl.tooth_reference or '').split(',')[0].strip() or {'retainer': '11'}.get(rtype, '36')
        if not tooth.isdigit():
            tooth = '11'
        order_day = self.today - timedelta(days=self.rng.randint(3, 25))
        order = self.env['dental.lab.order'].with_env(denv).create({
            'case_id': case.id, 'patient_id': case.patient_id.id, 'treatment_plan_id': pl.plan_id.id,
            'dentist_id': pl.plan_id.doctor_id.id, 'order_date': order_day,
            'due_date': self.today + timedelta(days=self.rng.randint(-2, 10)),
            'lab_type': 'external' if external else 'in_house', 'external_lab_id': external.id if external else False,
            'impression_type': self.rng.choice(['digital', 'physical_silicone', 'digital']),
            'shade': self.rng.choice(['A1', 'A2', 'A2', 'A3', 'B1']), 'priority': self.rng.choice(['0', '1', '2']),
            'margin_design': 'chamfer', 'occlusal_clearance': 'normal', 'bite_registration': True,
            'antagonist_impression': True,
            'technician_id': (self.users.get('labtech') or self.admin).id,
            'clinical_instructions': 'Please match adjacent teeth; light contact with antagonist.',
            'line_ids': [Command.create({'tooth_number': tooth, 'restoration_type': rtype, 'material': material_map[rtype],
                                         'quantity': 1, 'unit_price': pl.treatment_id.list_price * 0.3})],
        })
        if target == 'draft':
            return order
        order.action_submit()
        if target in ('submitted', 'cancelled'):
            if target == 'cancelled':
                order.action_cancel()
            return order
        lab = order.with_env(self._env_as(self.users.get('labtech')))
        lab.action_start_production()
        if target == 'in_production':
            return order
        lab.action_request_qc()
        if target == 'qc_pending':
            return order
        if target == 'rework':
            lab.quality_check_ids[:1].write({'quality_state': 'fail'})
            lab.quality_check_ids[1:].write({'quality_state': 'pass'})
            lab._check_all_qc_status()
            return order
        lab.quality_check_ids.write({'quality_state': 'pass'})
        lab._check_all_qc_status()
        lab.action_receive_finished_goods()
        if target == 'finished':
            return order
        lab.action_create_dispatch()
        if target == 'dispatched':
            return order
        rec = order.with_env(self._env_as(self.users.get('reception')))
        rec.action_receive_at_clinic()
        if target == 'received_clinic':
            return order
        order.write({'dentist_fit_rating': self.rng.choice(['excellent', 'good']), 'dentist_shade_match': 'perfect',
                     'dentist_acceptance_notes': 'Good marginal fit, contacts and occlusion verified.'})
        order.action_record_dentist_acceptance()
        if target == 'closed':
            order.action_close_order()
        return order

    # ------------------------------------------------------------------ ortho
    def create_ortho(self):
        lines = self.env['dental.treatment.plan.line'].search(
            [('treatment_id', '=', self._treat('treatment_braces').id if self._treat('treatment_braces') else 0)], order='id')
        cases = lines.mapped('plan_id.case_id')
        # Make sure there are a few ortho patients even if the random history had few
        if len(cases) < 5:
            busy = self.env['dental.case'].search([('state', 'in', ('draft', 'open', 'under_treatment'))]).patient_id
            candidates = self.patients.filtered(lambda p: 11 <= (p.age or 0) <= 35 and p not in busy)
            for patient in candidates[:5 - len(cases)]:
                day = self.today - timedelta(days=self.rng.randint(20, 40))
                while day.weekday() == 6:
                    day -= timedelta(days=1)
                doc_key = 'ananya' if 'ananya' in self.doctors else 'admin'
                start = self._free_slot(self.doctors[doc_key], day)
                if start:
                    self._step('ortho visit', self._history_visit, patient, doc_key, 'ortho', start, day)
            lines = self.env['dental.treatment.plan.line'].search(
                [('treatment_id', '=', self._treat('treatment_braces').id)], order='id')
        targets = ['active', 'active', 'planned', 'retention', 'assessment', 'active']
        for i, line in enumerate(lines[:len(targets)]):
            self._step('ortho chart %d' % i, self._ortho_chart, line, targets[i])

    def _ortho_chart(self, line, target):
        plan = line.plan_id
        doctor_user = next((self.users[k] for k, d in self.doctors.items() if d.id == plan.doctor_id.id), self.admin)
        denv = self._env_as(doctor_user)
        Chart = self.env['dental.ortho.chart'].with_env(denv)
        chart = Chart.search([('plan_line_id', '=', line.id)], limit=1) or Chart.create({
            'patient_id': plan.patient_id.id, 'case_id': plan.case_id.id, 'treatment_plan_id': plan.id,
            'plan_line_id': line.id, 'doctor_id': plan.doctor_id.id,
            'chief_concern': 'Crowded upper front teeth; wants a straighter smile.',
            'angle_class': self.rng.choice(['class_1', 'class_2_div1', 'class_2_div1', 'class_3']),
            'skeletal_pattern': self.rng.choice(['class_1', 'class_2']), 'vertical_pattern': 'normal',
            'profile': self.rng.choice(['straight', 'convex']),
            'molar_right': 'class_2_half', 'molar_left': 'class_1', 'canine_right': 'class_2_half', 'canine_left': 'class_1',
            'overjet': round(self.rng.uniform(3, 7), 1), 'overbite': round(self.rng.uniform(2, 5), 1),
            'crowding_upper': round(self.rng.uniform(3, 7), 1), 'crowding_lower': round(self.rng.uniform(2, 5), 1),
            'iotn_dhc': self.rng.choice(['3', '4', '4', '5']), 'crossbite': 'none',
            'upper_midline': 'centered', 'lower_midline': self.rng.choice(['centered', 'left']),
            'appliance_type': self.rng.choice(['fixed_metal', 'fixed_ceramic', 'self_ligating', 'aligners']),
            'bracket_prescription': 'mbt', 'slot_size': '022', 'anchorage': 'moderate',
            'extraction_plan': self.rng.choice(['none', 'none', 'u4_l4']), 'estimated_months': self.rng.choice([14, 18, 20, 24]),
            'visit_interval_weeks': 4, 'consent_given': True, 'retention_review_months': 3,
            'retainer_upper': 'essix', 'retainer_lower': 'bonded', 'retention_wear': 'nights',
            'treatment_objectives': 'Relieve crowding, correct overjet, achieve Class I canines and coincident midlines.',
            'diagnosis_summary': 'Class II div 1 malocclusion with moderate crowding.',
        })
        if target == 'assessment':
            return chart
        chart.action_confirm_plan()
        if target == 'planned':
            return chart
        months_ago = self.rng.randint(4, 10) if target == 'active' else 18
        bond_day = self.today - timedelta(days=30 * months_ago)
        chart.action_bond(bond_date=bond_day)
        Visit = self.env['dental.ortho.visit'].with_env(denv)
        wires = [('niti_014', 'niti_014'), ('niti_016', 'niti_016'), ('niti_16x22', 'niti_016'),
                 ('niti_19x25', 'niti_16x22'), ('ss_19x25', 'niti_19x25'), ('ss_19x25', 'ss_19x25')]
        n = min(months_ago, len(wires))
        for k in range(n):
            up, low = wires[k]
            Visit.create({
                'chart_id': chart.id, 'doctor_id': plan.doctor_id.id,
                'date': self._utc(bond_day + timedelta(days=28 * k), 11),
                'visit_type': 'bonding' if k == 0 else 'adjustment', 'upper_wire': up, 'lower_wire': low,
                'ligation': 'elastomeric', 'elastics': 'class_2' if k >= 3 else 'none',
                'elastic_wear': 'fulltime' if k >= 3 else False,
                'compliance': self.rng.choice(['good', 'good', 'fair']), 'hygiene': self.rng.choice(['good', 'fair']),
                'procedures': 'Wire change, re-ligation.' if k else 'Full arch bonding, initial NiTi wires placed.',
                'progress_notes': 'Alignment progressing as planned.', 'next_visit_weeks': 4, 'state': 'done',
                'patient_instructions': 'Avoid hard and sticky foods. Brush after every meal.',
            })
        chart.start_date = bond_day
        if target == 'retention':
            chart.action_start_retention()
            chart.debond_date = self.today - timedelta(days=30)
        return chart

    # ------------------------------------------------------------------ second opinions
    def create_second_opinions(self):
        if 'sara' not in self.doctors:
            return
        cases = self.env['dental.case'].search([('treatment_plan_ids', '!=', False)], order='id')
        scenarios = [
            # requester, specialist, target state
            ('admin', 'sara', 'draft'), ('admin', 'sara', 'submitted'), ('vikram', 'sara', 'in_review'),
            ('ananya', 'sara', 'opinion_submitted'), ('admin', 'sara', 'closed'),
            ('vikram', 'admin', 'submitted'), ('sara', 'admin', 'in_review'), ('ananya', 'admin', 'closed'),
        ]
        used = set()
        for req_key, spec_key, target in scenarios:
            if req_key not in self.doctors or spec_key not in self.doctors:
                continue
            case = cases.filtered(lambda c: c.doctor_id.id == self.doctors[req_key].id and c.id not in used)[:1] or \
                cases.filtered(lambda c: c.id not in used)[:1]
            if not case:
                break
            used.add(case.id)
            self._step('second opinion', self._second_opinion, case, req_key, spec_key, target)

    def _second_opinion(self, case, req_key, spec_key, target):
        req_env = self._env_as(self.users[req_key])
        spec_env = self._env_as(self.users[spec_key])
        plan = case.treatment_plan_ids[:1]
        so = self.env['dental.second.opinion'].with_env(req_env).create({
            'case_id': case.id, 'specialist_id': self.doctors[spec_key].id,
            'requesting_user_id': self.users[req_key].id, 'treatment_plan_id': plan.id or False,
            'priority': self.rng.choice(['0', '1', '2']),
            'due_date': self.today + timedelta(days=self.rng.randint(1, 6)),
            'clinical_question': self.rng.choice([
                'Is the tooth restorable with RCT and crown, or is extraction and implant the better long-term option?',
                'Please review the CBCT: is the ridge adequate for a 4.1 mm implant without grafting?',
                'Would you recommend surgical removal under LA, given the proximity to the IAN canal?',
                'Extraction vs non-extraction orthodontic plan - which would you advise?',
            ]),
            'clinical_summary': case.chief_complaint,
        })
        if target == 'draft':
            return so
        so.action_submit()
        if target == 'submitted':
            return so
        so = so.with_env(spec_env)
        so.action_start_review()
        if target == 'in_review':
            return so
        so.write({'findings': '<p>Reviewed radiographs and clinical notes. Periapical status favourable.</p>',
                  'recommendations': '<p>Proceed with the proposed plan; review in 6 weeks.</p>',
                  'recommended_action': self.rng.choice(['agree', 'modify'])})
        so.action_submit_opinion()
        if target == 'opinion_submitted':
            return so
        so.with_env(req_env).action_record_decision('accepted', 'Plan discussed with the patient; proceeding as advised.')
        return so
