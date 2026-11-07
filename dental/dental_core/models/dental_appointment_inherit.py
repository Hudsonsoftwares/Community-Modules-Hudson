from datetime import datetime, date, time, timedelta
import calendar
import pytz
from odoo import models, fields, api, _

class DentalAppointment(models.Model):
    _inherit = 'dental.appointment'

    case_ids = fields.One2many('dental.case', 'appointment_id', string='Clinical Cases')
    case_count = fields.Integer(string='Case Count', compute='_compute_case_count')
    lead_id = fields.Many2one(
        'crm.lead',
        string='Originating CRM Enquiry',
        copy=False,
        tracking=True,
        help="The CRM enquiry or lead from which this appointment was booked."
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for appt in records:
            if appt.lead_id:
                lead = appt.lead_id
                lead.write({
                    'appointment_id': appt.id,
                    'conversion_status': 'appointment_scheduled',
                })
                # If lead stage is at sequence 1 (New), advance to next stage (Qualified)
                if lead.stage_id and not lead.stage_id.is_won:
                    next_stage = self.env['crm.stage'].search([
                        ('sequence', '>', lead.stage_id.sequence),
                        ('is_won', '=', False)
                    ], order='sequence asc', limit=1)
                    if next_stage:
                        lead.stage_id = next_stage.id
                lead.message_post(body=_(
                    "Dental appointment <b>%s</b> scheduled for %s on %s."
                ) % (appt.name, appt.patient_id.name or 'Patient', appt.date_start))
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'state' in vals:
            for appt in self:
                if appt.lead_id:
                    if vals['state'] == 'completed':
                        appt.lead_id.write({'conversion_status': 'appointment_completed'})
                        appt.lead_id.message_post(body=_(
                            "Appointment <b>%s</b> was completed."
                        ) % appt.name)
                    elif vals['state'] == 'cancelled':
                        appt.lead_id.message_post(body=_(
                            "Appointment <b>%s</b> was cancelled. Status retained for receptionist follow-up."
                        ) % appt.name)
        return res

    @api.depends('case_ids')
    def _compute_case_count(self):
        for appt in self:
            appt.case_count = len(appt.case_ids)

    def action_open_clinical_case(self):
        self.ensure_one()
        CaseObj = self.env['dental.case']
        if self.case_ids:
            # Open existing case
            case = self.case_ids[0]
            # Backfill any empty medical history / chief complaints from appointment and patient
            vals_to_update = {}
            if not case.chief_complaint:
                cc = CaseObj._extract_chief_complaint_from_appointment(self)
                if cc:
                    vals_to_update['chief_complaint'] = cc
            if self.patient_id:
                if not case.medical_history_summary:
                    med = CaseObj._extract_medical_history_from_patient(self.patient_id)
                    if med:
                        vals_to_update['medical_history_summary'] = med
                if not case.allergies:
                    allergies = CaseObj._extract_allergies_from_patient(self.patient_id)
                    if allergies:
                        vals_to_update['allergies'] = allergies
                if not case.current_medications:
                    meds = CaseObj._extract_medications_from_patient(self.patient_id)
                    if meds:
                        vals_to_update['current_medications'] = meds
                if not case.dental_history_summary:
                    dh = CaseObj._extract_dental_history_from_patient(self.patient_id)
                    if dh:
                        vals_to_update['dental_history_summary'] = dh
            if vals_to_update:
                case.write(vals_to_update)

            action = self.env['ir.actions.act_window']._for_xml_id('dental_core.action_dental_case')
            action['res_id'] = case.id
            action['views'] = [(self.env.ref('dental_core.view_dental_case_form').id, 'form')]
            return action
        else:
            # Create a new case
            case_vals = {
                'patient_id': self.patient_id.id,
                'doctor_id': self.doctor_id.id,
                'appointment_id': self.id,
                'branch_id': self.branch_id.id,
                'chief_complaint': CaseObj._extract_chief_complaint_from_appointment(self),
                'medical_history_summary': CaseObj._extract_medical_history_from_patient(self.patient_id) if self.patient_id else False,
                'allergies': CaseObj._extract_allergies_from_patient(self.patient_id) if self.patient_id else False,
                'current_medications': CaseObj._extract_medications_from_patient(self.patient_id) if self.patient_id else False,
                'dental_history_summary': CaseObj._extract_dental_history_from_patient(self.patient_id) if self.patient_id else False,
            }
            case = CaseObj.create(case_vals)
            action = self.env['ir.actions.act_window']._for_xml_id('dental_core.action_dental_case')
            action['res_id'] = case.id
            action['views'] = [(self.env.ref('dental_core.view_dental_case_form').id, 'form')]
            return action

    def action_start_consultation(self):
        res = super().action_start_consultation()
        if len(self) == 1:
            return self.action_open_clinical_case()
        return res

    @api.model
    def get_admin_dashboard_data(self, branch_id=None):
        """
        Fetches live operational, clinical, and statistical data for the 
        Executive Dental Hospital Admin Dashboard.
        """
        company = self.env['res.company'].browse(branch_id) if branch_id else self.env.company
        today = fields.Date.today()
        user_tz = pytz.timezone(self.env.user.tz or 'UTC')

        # Local start/end of today in UTC
        start_local = user_tz.localize(datetime.combine(today, time.min))
        end_local = user_tz.localize(datetime.combine(today, time.max))
        utc_start = start_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        utc_end = end_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')

        # Domain filters
        appt_domain = [
            ('date_start', '>=', utc_start),
            ('date_start', '<=', utc_end),
            ('branch_id', '=', company.id)
        ]

        # 1. Appointments counts
        appts_today = self.search(appt_domain, order='date_start asc')
        total_appts_today = len(appts_today)

        # In consultation / chairs
        in_consultation_count = sum(1 for a in appts_today if a.state == 'in_consultation')
        checked_in_count = sum(1 for a in appts_today if a.state == 'checked_in')
        completed_count = sum(1 for a in appts_today if a.state == 'completed')
        cancelled_count = sum(1 for a in appts_today if a.state == 'cancelled')

        # Follow-ups (Pending followups for clinic)
        followups_count = 0
        try:
            followups_count = self.env['dental.follow.up'].search_count([
                ('company_id', '=', company.id),
                ('state', '=', 'pending'),
                ('date', '<=', today)
            ])
        except Exception:
            pass
        if followups_count == 0:
            followups_count = sum(1 for a in appts_today if 'follow' in (a.reason or '').lower() or (a.treatment_id and 'follow' in (a.treatment_id.name or '').lower()))

        # 2. Patients (New & Total created today)
        new_patients_today = self.env['res.partner'].search_count([
            ('is_dental_patient', '=', True),
            ('create_date', '>=', utc_start),
            ('create_date', '<=', utc_end),
        ])

        # 3. Clinical Cases
        active_clinical_cases = self.env['dental.case'].search_count([
            ('state', 'in', ['open', 'under_treatment']),
            ('branch_id', '=', company.id)
        ])

        # 4. Prescriptions today
        prescriptions_count = 0
        try:
            prescriptions_count = self.env['dental.prescription'].search_count([
                ('company_id', '=', company.id),
                '|',
                ('prescription_date', '=', today),
                ('create_date', '>=', utc_start)
            ])
        except Exception:
            pass

        # 5. Lab Tests today
        lab_orders_count = 0
        try:
            lab_orders_count = self.env['dental.lab.order'].search_count([
                ('company_id', '=', company.id),
                '|',
                ('order_date', '=', today),
                ('create_date', '>=', utc_start)
            ])
        except Exception:
            pass

        # 6. Radiology (X-Ray) Today
        xray_count = self.env['ir.attachment'].search_count([
            ('res_model', 'in', ['dental.case', 'dental.clinical.examination', 'dental.treatment.plan', 'res.partner']),
            '|',
            ('mimetype', 'like', 'image%'),
            ('name', 'ilike', '%x-ray%')
        ])

        # Total OPD Visits today
        opd_visits_count = total_appts_today
        display_total_appts = total_appts_today

        # Chairs capacity
        total_chairs = 16
        occupied_chairs = min(in_consultation_count, total_chairs)
        chairs_occupancy_pct = int((occupied_chairs / total_chairs) * 100) if total_chairs > 0 else 0

        # Today's appointments list formatted
        appointments_list = []
        status_map = {
            'checked_in': {'label': 'Checked In', 'class': 'badge-checked-in'},
            'waiting': {'label': 'Waiting', 'class': 'badge-waiting'},
            'in_consultation': {'label': 'Ongoing', 'class': 'badge-ongoing'},
            'confirmed': {'label': 'Scheduled', 'class': 'badge-scheduled'},
            'pending': {'label': 'Scheduled', 'class': 'badge-scheduled'},
            'completed': {'label': 'Completed', 'class': 'badge-completed'},
            'cancelled': {'label': 'Cancelled', 'class': 'badge-cancelled'},
        }

        if appts_today:
            for a in appts_today[:8]:
                appt_time = fields.Datetime.context_timestamp(self, a.date_start).strftime('%H:%M') if a.date_start else ''
                st = a.state or 'confirmed'
                st_info = status_map.get(st, {'label': st.replace('_', ' ').title(), 'class': 'badge-scheduled'})
                t_name = a.treatment_id.name if a.treatment_id else (a.reason or 'Consultation')
                if isinstance(t_name, dict):
                    t_name = t_name.get('en_US', 'Consultation')
                appointments_list.append({
                    'id': a.id,
                    'time': appt_time,
                    'patient_id': a.patient_id.id,
                    'patient_name': a.patient_id.name,
                    'treatment': t_name,
                    'state': st,
                    'status_label': st_info['label'],
                    'status_class': st_info['class'],
                    'doctor_name': a.doctor_id.name or 'Dentist'
                })

        # Recent Patients (Real records from DB)
        recent_patients_list = []
        recent_partners = self.env['res.partner'].search(
            [('is_dental_patient', '=', True)],
            order='create_date desc, id desc',
            limit=5
        )

        for p in recent_partners:
            time_str = fields.Datetime.context_timestamp(self, p.create_date).strftime('%d %b %H:%M') if p.create_date else ''
            recent_patients_list.append({
                'id': p.id,
                'name': p.name,
                'treatment': 'Dental Patient',
                'time': time_str,
                'badge': 'Patient'
            })

        # Branches
        all_branches = [{'id': c.id, 'name': c.name} for c in self.env['res.company'].search([])]

        # Date string
        now_dt = fields.Date.today()
        weekday_name = now_dt.strftime('%a')
        month_name = now_dt.strftime('%b')
        formatted_date = f"{weekday_name}, {now_dt.day} {month_name} {now_dt.year}"

        # Real comparison vs yesterday for trend percentages
        yesterday = today - timedelta(days=1)
        yest_s = user_tz.localize(datetime.combine(yesterday, time.min)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        yest_e = user_tz.localize(datetime.combine(yesterday, time.max)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        yest_appts = self.search_count([('date_start', '>=', yest_s), ('date_start', '<=', yest_e), ('branch_id', '=', company.id)])

        def calc_trend(curr, prev):
            if prev > 0:
                pct = round(abs((curr - prev) / prev) * 100)
                d = 'up' if curr >= prev else 'down'
                return pct, d
            return 0, 'up'

        appts_trend_pct, appts_trend_dir = calc_trend(total_appts_today, yest_appts)

        # Real 6-day historical sparklines from database
        six_days_ago = today - timedelta(days=5)
        appt_sparkline = []
        rx_sparkline = []
        lab_sparkline = []
        rad_sparkline = []
        for i in range(6):
            cur_d = six_days_ago + timedelta(days=i)
            cur_s = user_tz.localize(datetime.combine(cur_d, time.min)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
            cur_e = user_tz.localize(datetime.combine(cur_d, time.max)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
            c_app = self.search_count([('date_start', '>=', cur_s), ('date_start', '<=', cur_e), ('branch_id', '=', company.id)])
            appt_sparkline.append(c_app)
            try:
                c_rx = self.env['dental.prescription'].search_count([
                    ('company_id', '=', company.id),
                    ('prescription_date', '=', cur_d)
                ])
            except Exception:
                c_rx = 0
            rx_sparkline.append(c_rx)
            try:
                c_lab = self.env['dental.lab.order'].search_count([
                    ('company_id', '=', company.id),
                    ('order_date', '=', cur_d)
                ])
            except Exception:
                c_lab = 0
            lab_sparkline.append(c_lab)
            c_rad = self.env['ir.attachment'].search_count([
                ('res_model', 'in', ['dental.case', 'dental.clinical.examination', 'dental.treatment.plan', 'res.partner']),
                ('create_date', '>=', cur_s),
                ('create_date', '<=', cur_e),
                '|', ('mimetype', 'like', 'image%'), ('name', 'ilike', '%x-ray%')
            ])
            rad_sparkline.append(c_rad)

        # Real hourly distribution from today's appointments
        hourly_slots = [
            {'hour': '8AM', 'start': 8, 'end': 10, 'count': 0},
            {'hour': '10AM', 'start': 10, 'end': 12, 'count': 0},
            {'hour': '12PM', 'start': 12, 'end': 14, 'count': 0},
            {'hour': '2PM', 'start': 14, 'end': 16, 'count': 0},
            {'hour': '4PM', 'start': 16, 'end': 18, 'count': 0},
            {'hour': '6PM', 'start': 18, 'end': 20, 'count': 0},
        ]
        for a in appts_today:
            if a.date_start:
                a_local = pytz.utc.localize(a.date_start).astimezone(user_tz)
                h = a_local.hour
                for s in hourly_slots:
                    if s['start'] <= h < s['end']:
                        s['count'] += 1
                        break

        hourly_points = [{'hour': s['hour'], 'count': s['count']} for s in hourly_slots]
        max_slot = max(hourly_slots, key=lambda s: s['count'])
        peak_time = f"{max_slot['hour'].replace('AM', ':00 AM').replace('PM', ':00 PM')}" if max_slot['count'] > 0 else '—'
        peak_count = max_slot['count']

        unread_notifs = self.env['mail.activity'].search_count([
            ('user_id', '=', self.env.uid),
            ('date_deadline', '<=', today)
        ])

        return {
            'header': {
                'clinic_name': company.name or 'Dental Hospital',
                'current_branch_id': company.id,
                'current_branch_name': company.name or 'Main Branch',
                'branches': all_branches,
                'user_name': self.env.user.name or 'Admin',
                'user_initial': (self.env.user.name or 'A')[0].upper(),
                'unread_notifications': unread_notifs,
                'date_str': formatted_date,
            },
            'floorplan': {
                'opd': {'count': opd_visits_count, 'capacity': 24, 'status': 'normal'},
                'chairs': {'occupied': occupied_chairs, 'total': total_chairs, 'status': 'normal'},
                'radiology': {'count': min(xray_count, 4), 'capacity': 4, 'status': 'normal'},
                'lab': {'count': min(lab_orders_count, 6), 'capacity': 6, 'status': 'warning' if lab_orders_count > 0 else 'normal'},
                'reception': {'waiting': checked_in_count, 'label': f"{checked_in_count} Waiting", 'status': 'info'},
                'clinical': {'active': active_clinical_cases, 'capacity': 8, 'status': 'normal'},
                'pharmacy': {'status': 'Active', 'count': prescriptions_count},
                'sterilization': {'status': 'Active'},
            },
            'kpis': {
                'opd_patients': {
                    'val': opd_visits_count,
                    'trend_pct': appts_trend_pct,
                    'trend_label': 'vs yesterday',
                    'trend_dir': appts_trend_dir,
                    'sparkline': appt_sparkline
                },
                'appointments': {
                    'val': display_total_appts,
                    'trend_pct': appts_trend_pct,
                    'trend_label': 'vs yesterday',
                    'trend_dir': appts_trend_dir,
                    'sparkline': appt_sparkline
                },
                'chairs_occupancy': {
                    'pct': chairs_occupancy_pct,
                    'occupied': occupied_chairs,
                    'total': total_chairs,
                    'label': f"{occupied_chairs} / {total_chairs} chairs in use"
                },
                'prescriptions': {
                    'val': prescriptions_count,
                    'trend_pct': 0,
                    'trend_label': 'vs yesterday',
                    'trend_dir': 'up',
                    'sparkline': rx_sparkline
                },
                'lab_tests': {
                    'val': lab_orders_count,
                    'trend_pct': 0,
                    'trend_label': 'vs yesterday',
                    'trend_dir': 'up',
                    'sparkline': lab_sparkline
                },
                'radiology': {
                    'val': xray_count,
                    'trend_pct': 0,
                    'trend_label': 'vs yesterday',
                    'trend_dir': 'up',
                    'sparkline': rad_sparkline
                }
            },
            'patient_flow': {
                'filter': 'Today',
                'peak_time': peak_time,
                'peak_count': peak_count,
                'opd_visits': opd_visits_count,
                'new_patients': new_patients_today,
                'follow_ups': followups_count,
                'cancellations': cancelled_count,
                'hourly_points': hourly_points
            },
            'today_appointments': appointments_list[:5],
            'recent_patients': recent_patients_list[:5]
        }

    def action_call_patient(self):
        for record in self:
            record.write({
                'called_time': fields.Datetime.now(),
            })
        return True

    @api.model
    def get_reception_dashboard_data(self, branch_id=None):
        company = self.env['res.company'].browse(branch_id) if branch_id else self.env.company
        today = fields.Date.today()
        user_tz = pytz.timezone(self.env.user.tz or 'Asia/Kolkata')

        # Local day boundaries in UTC
        start_local = user_tz.localize(datetime.combine(today, time.min))
        end_local = user_tz.localize(datetime.combine(today, time.max))
        utc_start = start_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        utc_end = end_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')

        # 1. Real appointments today
        domain = [
            ('date_start', '>=', utc_start),
            ('date_start', '<=', utc_end),
        ]
        if branch_id:
            domain.append(('branch_id', '=', company.id))

        appts = self.search(domain, order='date_start asc')
        total_today = len(appts)

        checked_in_appts = appts.filtered(lambda a: a.state == 'checked_in')
        in_consultation_appts = appts.filtered(lambda a: a.state == 'in_consultation')
        completed_appts = appts.filtered(lambda a: a.state == 'completed')
        scheduled_appts = appts.filtered(lambda a: a.state in ['pending', 'confirmed'])

        checked_in_count = len(checked_in_appts)
        waiting_count = len(checked_in_appts)
        arrivals_count = len(checked_in_appts) + len(in_consultation_appts) + len(completed_appts)

        # 2. Real new patients created today
        new_registrations = self.env['res.partner'].search_count([
            ('is_dental_patient', '=', True),
            ('create_date', '>=', utc_start),
            ('create_date', '<=', utc_end),
        ])

        # 3. Real follow-ups due
        follow_ups_count = 0
        try:
            follow_ups_count = self.env['dental.follow.up'].search_count([
                ('company_id', '=', company.id),
                ('state', '=', 'pending'),
                ('date', '<=', today)
            ])
        except Exception:
            pass

        # 4. Real patients needing registration among today's visitors
        today_patient_ids = appts.mapped('patient_id').ids
        needs_registration_count = 0
        if today_patient_ids:
            needs_registration_count = self.env['res.partner'].search_count([
                ('id', 'in', today_patient_ids),
                '|', '|',
                ('dental_patient_id', '=', False),
                ('dental_patient_id', '=', 'New'),
                ('dental_patient_id', '=', '')
            ])

        # 5. Live Patient Queue list
        active_waiting = checked_in_appts.sorted(key=lambda a: (a.queue_priority, a.date_start), reverse=True)
        active_in_consult = in_consultation_appts.sorted(key=lambda a: a.date_start)
        upcoming_scheduled = scheduled_appts.sorted(key=lambda a: a.date_start)

        all_queue_appts = list(active_waiting) + list(active_in_consult) + list(upcoming_scheduled)

        next_token = "—"
        if active_waiting and active_waiting[0].token_number:
            next_token = active_waiting[0].token_number
        elif upcoming_scheduled and upcoming_scheduled[0].token_number:
            next_token = upcoming_scheduled[0].token_number

        queue_list = []
        for idx, a in enumerate(all_queue_appts[:15]):
            tok = a.token_number or a.name or f"#{idx+1}"

            start_utc = pytz.utc.localize(a.date_start)
            start_user = start_utc.astimezone(user_tz)
            time_display = start_user.strftime('%I:%M %p')

            treatment_title = 'Consultation'
            if a.treatment_id:
                tname = a.treatment_id.name
                if isinstance(tname, dict):
                    treatment_title = tname.get('en_US') or list(tname.values())[0]
                else:
                    treatment_title = str(tname)
            elif a.reason:
                treatment_title = a.reason

            # Real state and action mapping:
            if a.state == 'checked_in':
                if idx == 0 and active_waiting and a.id == active_waiting[0].id:
                    status_key = 'next'
                    status_label = 'Next'
                    badge_class = 'badge-next'
                    action_type = 'call_now'
                    action_label = 'Call Now'
                else:
                    status_key = 'checked_in'
                    status_label = 'Checked In'
                    badge_class = 'badge-checked-in'
                    action_type = 'start_visit'
                    action_label = 'Start Visit'
            elif a.state == 'in_consultation':
                status_key = 'in_consultation'
                status_label = 'In Consultation'
                badge_class = 'badge-consultation'
                action_type = 'start_visit'
                action_label = 'In Visit'
            elif a.state in ['confirmed', 'pending']:
                status_key = 'waiting'
                status_label = 'Scheduled' if a.state == 'pending' else 'Confirmed'
                badge_class = 'badge-waiting'
                action_type = 'check_in'
                action_label = 'Check In'
            elif a.state == 'completed':
                status_key = 'completed'
                status_label = 'Completed'
                badge_class = 'badge-checked-in'
                action_type = 'manage'
                action_label = 'Manage'
            else:
                status_key = 'other'
                status_label = a.state.capitalize()
                badge_class = 'badge-waiting'
                action_type = 'manage'
                action_label = 'Manage'

            queue_list.append({
                'id': a.id,
                'index': idx + 1,
                'token': tok,
                'patient_id': a.patient_id.id,
                'patient_name': a.patient_id.name or 'Unknown',
                'patient_phone': a.patient_id.phone or '',
                'appointment_info': f"{treatment_title} {time_display}",
                'treatment_name': treatment_title,
                'time_display': time_display,
                'state': a.state,
                'status_key': status_key,
                'status_label': status_label,
                'badge_class': badge_class,
                'action_type': action_type,
                'action_label': action_label,
            })

        # 6. Real Today's Appointments Timeline
        timeline_list = []
        for a in appts:
            start_utc = pytz.utc.localize(a.date_start)
            start_user = start_utc.astimezone(user_tz)
            time_display = start_user.strftime('%I:%M %p')

            treatment_title = 'Consultation'
            if a.treatment_id:
                tname = a.treatment_id.name
                if isinstance(tname, dict):
                    treatment_title = tname.get('en_US') or list(tname.values())[0]
                else:
                    treatment_title = str(tname)
            elif a.reason:
                treatment_title = a.reason

            if a.state == 'completed':
                status_label = 'Completed'
                status_class = 'status-completed'
                dot_class = 'dot-completed'
            elif a.state == 'checked_in':
                status_label = 'Checked In'
                status_class = 'status-checked-in'
                dot_class = 'dot-checked-in'
            elif a.state == 'in_consultation':
                status_label = 'In Consultation'
                status_class = 'status-consultation'
                dot_class = 'dot-consultation'
            else:
                status_label = 'Scheduled' if a.state == 'pending' else 'Confirmed'
                status_class = 'status-scheduled'
                dot_class = 'dot-scheduled'

            timeline_list.append({
                'id': a.id,
                'time_display': time_display,
                'patient_id': a.patient_id.id,
                'patient_name': a.patient_id.name or 'Unknown',
                'treatment_name': treatment_title,
                'state': a.state,
                'status_label': status_label,
                'status_class': status_class,
                'dot_class': dot_class,
            })

        # 7. Doctors Availability for Reception Desk
        all_dentists = self.env['hr.employee'].sudo().search([('is_dentist', '=', True), ('active', '=', True)], order='id asc')
        now_utc = fields.Datetime.now()
        doctors_availability = []
        for doc in all_dentists:
            avatar = f'/web/image?model=hr.employee&field=avatar_128&id={doc.id}'

            # Check approved leave
            on_leave = self.env['hr.leave'].sudo().search([
                ('employee_id', '=', doc.id),
                ('state', '=', 'validate'),
                ('date_from', '<=', now_utc),
                ('date_to', '>=', now_utc),
            ], limit=1)

            # Check active consultation right now
            in_consult = appts.filtered(lambda a: a.doctor_id.id == doc.id and a.state == 'in_consultation')
            # Doctor's appointments today
            doc_appts = appts.filtered(lambda a: a.doctor_id.id == doc.id)

            if on_leave:
                status_code = 'on_leave'
                status_label = 'On Leave'
                badge_class = 'badge-leave'
            elif in_consult:
                status_code = 'busy'
                pat_name = in_consult[0].patient_id.name or 'Patient'
                status_label = f'In Visit ({pat_name.split()[0]})'
                badge_class = 'badge-busy'
            else:
                status_code = 'available'
                status_label = 'Available Now'
                badge_class = 'badge-available'

            doctors_availability.append({
                'id': doc.id,
                'name': doc.name,
                'specialization': doc.specialization or 'Dentist',
                'avatar_url': avatar,
                'status_code': status_code,
                'status_label': status_label,
                'badge_class': badge_class,
                'today_appointments': len(doc_appts),
                'phone': doc.work_phone or '',
            })

        # 8. Real CRM Enquiries & Follow-ups for Reception Desk
        crm_domain = [('active', '=', True), ('type', 'in', ('opportunity', 'lead'))]
        if branch_id:
            crm_domain.append(('company_id', 'in', [company.id, False]))

        open_leads = self.env['crm.lead'].search(crm_domain, order='create_date desc, id desc')
        new_enquiries = open_leads.filtered(lambda l: l.conversion_status == 'new' or (not l.appointment_id and l.conversion_status == 'contacted'))
        new_enquiries_count = len(new_enquiries)
        total_open_enquiries = len(open_leads.filtered(lambda l: (not l.stage_id or not l.stage_id.is_won) and l.conversion_status != 'cancelled'))

        # Enquiries converted into real appointments
        converted_enquiries = open_leads.filtered(lambda l: l.appointment_id or l.conversion_status in ('appointment_scheduled', 'appointment_completed'))
        converted_appointments_count = len(converted_enquiries)

        # Scheduled follow-up activities due or overdue
        today_date = fields.Date.today()
        lead_activities = self.env['mail.activity'].search([
            ('res_model', '=', 'crm.lead'),
            ('res_id', 'in', open_leads.ids),
            ('date_deadline', '<=', today_date)
        ]) if open_leads else self.env['mail.activity'].browse()
        due_followup_lead_ids = set(lead_activities.mapped('res_id'))
        crm_followups_due_count = len(open_leads.filtered(lambda l: l.id in due_followup_lead_ids or l.conversion_status == 'follow_up'))

        # Total combined follow-ups
        combined_followups = follow_ups_count + crm_followups_due_count

        # Sources Breakdown
        source_breakdown = {
            'Website': 0,
            'Phone Call': 0,
            'Walk-in': 0,
            'Patient Referral': 0,
            'Social Media': 0,
            'Other': 0,
        }
        for lead in open_leads:
            st = lead.source_type or ''
            sname = (lead.source_id.name or '').lower() if lead.source_id else ''
            if st == 'website' or 'web' in sname:
                source_breakdown['Website'] += 1
            elif st == 'phone' or 'phone' in sname:
                source_breakdown['Phone Call'] += 1
            elif st == 'walk_in' or 'walk' in sname:
                source_breakdown['Walk-in'] += 1
            elif st == 'referral' or 'refer' in sname:
                source_breakdown['Patient Referral'] += 1
            elif st in ('facebook', 'instagram') or 'facebook' in sname or 'instagram' in sname:
                source_breakdown['Social Media'] += 1
            else:
                source_breakdown['Other'] += 1

        # Format recent enquiries for live reception desk table
        source_labels = {
            'walk_in': ('Walk-in', 'badge-walkin'),
            'phone': ('Phone Call', 'badge-phone'),
            'website': ('Website', 'badge-website'),
            'referral': ('Referral', 'badge-referral'),
            'facebook': ('Facebook', 'badge-social'),
            'instagram': ('Instagram', 'badge-social'),
            'google': ('Google Search', 'badge-website'),
            'other': ('Other', 'badge-other'),
        }
        conv_labels = {
            'new': ('New Enquiry', 'status-new'),
            'contacted': ('Contacted', 'status-contacted'),
            'follow_up': ('Follow-up Due', 'status-followup'),
            'appointment_scheduled': ('Appt Booked', 'status-scheduled'),
            'appointment_completed': ('Completed', 'status-completed'),
            'cancelled': ('Cancelled', 'status-cancelled'),
        }

        crm_enquiries = []
        for l in open_leads[:50]:
            treatment_title = '—'
            if l.treatment_id:
                tname = l.treatment_id.name
                treatment_title = (tname.get('en_US') or list(tname.values())[0]) if isinstance(tname, dict) else str(tname)
            elif l.name:
                treatment_title = l.name

            doc_name = l.preferred_doctor_id.name if l.preferred_doctor_id else '—'
            next_act = l.activity_ids.sorted(key=lambda a: a.date_deadline)[:1]
            act_summary = next_act.summary or (next_act.activity_type_id.name if next_act else '')
            act_date_str = next_act.date_deadline.strftime('%d %b') if next_act and next_act.date_deadline else ''
            act_status = 'none'
            if next_act and next_act.date_deadline:
                if next_act.date_deadline < today_date:
                    act_status = 'overdue'
                elif next_act.date_deadline == today_date:
                    act_status = 'today'
                else:
                    act_status = 'planned'

            s_label, s_class = source_labels.get(l.source_type or '', (l.source_id.name if l.source_id else 'Enquiry', 'badge-other'))
            conv_status = l.conversion_status or 'new'
            c_label, c_class = conv_labels.get(conv_status, ('Open', 'status-contacted'))
            resp_name = l.user_id.name if l.user_id else '—'

            rec_date_str = ''
            if l.create_date:
                utc_dt = pytz.utc.localize(l.create_date)
                local_dt = utc_dt.astimezone(user_tz)
                rec_date_str = local_dt.strftime('%d %b, %I:%M %p')

            crm_enquiries.append({
                'id': l.id,
                'name': l.name or '',
                'contact_name': l.contact_name or l.partner_name or (l.patient_id.name if l.patient_id else False) or l.name or '—',
                'phone': l.phone or (l.patient_id.phone if l.patient_id else False) or (l.patient_id.mobile if l.patient_id else False) or l.mobile or '',
                'email': l.email_from or (l.patient_id.email if l.patient_id else False) or '',
                'source_type': l.source_type or 'other',
                'source_label': s_label,
                'source_class': s_class,
                'treatment_name': treatment_title,
                'doctor_name': doc_name,
                'user_name': resp_name,
                'stage_name': l.stage_id.name if l.stage_id else 'New',
                'conversion_status': conv_status,
                'conversion_label': c_label,
                'conversion_class': c_class,
                'activity_summary': act_summary,
                'activity_date': act_date_str,
                'activity_status': act_status,
                'has_matching_patient': l.has_matching_patient,
                'matching_patient_id': l.matching_patient_id.id if l.matching_patient_id else False,
                'matching_patient_name': l.matching_patient_id.name if l.matching_patient_id else False,
                'patient_id': l.patient_id.id if l.patient_id else False,
                'patient_name': l.patient_id.name if l.patient_id else False,
                'appointment_id': l.appointment_id.id if l.appointment_id else False,
                'appointment_name': l.appointment_id.name if l.appointment_id else False,
                'appointment_state': l.appointment_id.state if l.appointment_id else False,
                'received_date': rec_date_str,
            })

        # 8. Equipment under maintenance or unavailable in this branch
        equip_domain = ['|', ('company_id', '=', False), ('company_id', '=', company.id)]
        branch_equipments = self.env['maintenance.equipment'].search(equip_domain)
        unavailable_equips = branch_equipments.filtered(
            lambda e: (hasattr(e, 'is_available') and not e.is_available) or
                      (hasattr(e, 'equipment_condition') and e.equipment_condition in ('under_repair', 'out_of_order', 'scrapped'))
        )
        unavailable_equipment = [{
            'id': e.id,
            'name': e.name,
            'category_name': e.category_id.name if e.category_id else 'Equipment',
            'condition': getattr(e, 'equipment_condition', 'under_repair'),
            'serial_no': e.serial_no or '',
        } for e in unavailable_equips]

        return {
            'stats': {
                'today_appointments': total_today,
                'waiting_patients': waiting_count,
                'checked_in_patients': checked_in_count,
                'new_patients_today': new_registrations,
                'upcoming_follow_ups': combined_followups,
                'arrivals': arrivals_count,
                'needs_registration': needs_registration_count,
                'next_token': next_token,
                'crm_new_enquiries': new_enquiries_count,
                'crm_open_enquiries': total_open_enquiries,
                'crm_pending_followups': crm_followups_due_count,
                'crm_converted_appointments': converted_appointments_count,
                'unavailable_equipment_count': len(unavailable_equipment),
            },
            'queue_list': queue_list,
            'timeline_list': timeline_list,
            'doctors_availability': doctors_availability,
            'crm_enquiries': crm_enquiries,
            'crm_source_breakdown': source_breakdown,
            'unavailable_equipment': unavailable_equipment,
        }

    @api.model
    def get_waiting_queue_board_data(self, branch_id=None):
        """
        Fetches structured real-time queue data per doctor operatory for
        the Reception Desk Waiting Queue Screen and Future TV Display Board.
        """
        company = self.env['res.company'].browse(branch_id) if branch_id else self.env.company
        today = fields.Date.today()
        user_tz = pytz.timezone(self.env.user.tz or 'Asia/Kolkata')

        # Local day boundaries in UTC
        start_local = user_tz.localize(datetime.combine(today, time.min))
        end_local = user_tz.localize(datetime.combine(today, time.max))
        utc_start = start_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        utc_end = end_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')

        # Clinic header info
        partner = company.partner_id
        clinic_name = company.name or "Dental Hospital & Surgical Center"
        if clinic_name == 'My Company':
            clinic_name = "DenBell Multi-Speciality Dental Hospital"
        address_parts = [p for p in [partner.street, partner.city, partner.zip] if p]
        clinic_address = ", ".join(address_parts) if address_parts else "Main Clinic & Dental Surgery"

        # 1. Real appointments today
        domain = [
            ('date_start', '>=', utc_start),
            ('date_start', '<=', utc_end),
        ]
        if branch_id:
            domain.append(('branch_id', '=', company.id))

        today_appts = self.search(domain, order='date_start asc')
        total_patients_today = len(today_appts)
        now_serving_total = len(today_appts.filtered(lambda a: a.state == 'in_consultation'))
        waiting_total = len(today_appts.filtered(lambda a: a.state == 'checked_in'))
        completed_total = len(today_appts.filtered(lambda a: a.state == 'completed'))

        # Fetch active real doctors (strictly real doctors, no dummy records!)
        real_dentists = self.env['hr.employee'].sudo().search([
            ('is_dentist', '=', True),
            ('active', '=', True)
        ], order='id asc')

        # If any appointment has an assigned active employee who is acting as doctor, include them
        assigned_doc_ids = today_appts.mapped('doctor_id').ids
        extra_docs = self.env['hr.employee'].sudo().search([
            ('id', 'in', assigned_doc_ids),
            ('id', 'not in', real_dentists.ids),
            ('active', '=', True)
        ], order='id asc')
        all_active_doctors = real_dentists | extra_docs

        # Helper to format clean TV token
        def clean_token(appt, fallback_idx=1):
            raw = appt.token_number
            if raw:
                parts = raw.replace('/', '-').split('-')
                last_part = parts[-1]
                if last_part.isdigit():
                    return f"T-{int(last_part):03d}"
                return raw[:8].upper()
            assigned_tok = f"T-{appt.id % 1000:03d}" if appt.id else f"T-{fallback_idx:03d}"
            try:
                appt.sudo().write({'token_number': assigned_tok})
            except Exception:
                pass
            return assigned_tok

        # Helper to format demographic string e.g. (28F), (42M)
        def format_demographics(partner):
            if not partner:
                return ""
            parts = []
            age_val = getattr(partner, 'age', 0)
            if age_val and age_val > 0:
                parts.append(str(age_val))
            gender_val = getattr(partner, 'gender', False)
            if gender_val:
                g_code = 'M' if gender_val == 'male' else ('F' if gender_val == 'female' else 'O')
                if parts:
                    return f"({parts[0]}{g_code})"
                return f"({g_code})"
            elif parts:
                return f"({parts[0]}y)"
            return ""

        # Color palettes for operatories (modern clinic accents, bright and crisp)
        operatory_palettes = [
            {'name': 'Operatory 1', 'color': '#0284c7', 'bg_tint': '#f0f9ff', 'border': '#bae6fd'},
            {'name': 'Operatory 2', 'color': '#059669', 'bg_tint': '#ecfdf5', 'border': '#a7f3d0'},
            {'name': 'Operatory 3', 'color': '#d97706', 'bg_tint': '#fffbeb', 'border': '#fde68a'},
            {'name': 'Operatory 4', 'color': '#7c3aed', 'bg_tint': '#f5f3ff', 'border': '#ddd6fe'},
            {'name': 'Operatory 5', 'color': '#0891b2', 'bg_tint': '#ecfeff', 'border': '#a5f3fc'},
        ]

        doctors_data = []
        token_counter = 1

        for d_idx, doc in enumerate(all_active_doctors):
            palette = operatory_palettes[d_idx % len(operatory_palettes)]
            doc_appts = today_appts.filtered(lambda a: a.doctor_id.id == doc.id)

            spec = getattr(doc, 'specialization', False) or (doc.department_id.name if doc.department_id else 'Dental Surgeon')
            op_label = f"{spec} • {palette['name']}"

            # 1. Now Serving (in_consultation)
            in_consult = doc_appts.filtered(lambda a: a.state == 'in_consultation').sorted(
                key=lambda a: (a.called_time or a.date_start), reverse=True
            )
            now_serving = None
            if in_consult:
                curr = in_consult[0]
                t_tok = clean_token(curr, token_counter)
                token_counter += 1

                elapsed_mins = 0
                if curr.called_time:
                    diff = fields.Datetime.now() - curr.called_time
                    elapsed_mins = max(1, int(diff.total_seconds() / 60))

                now_serving = {
                    'id': curr.id,
                    'token': t_tok,
                    'raw_token': curr.token_number or t_tok,
                    'patient_id': curr.patient_id.id,
                    'patient_name': curr.patient_id.name or 'Unknown',
                    'demographics': format_demographics(curr.patient_id),
                    'treatment_name': curr.treatment_id.name or curr.reason or 'Dental Consultation',
                    'state': curr.state,
                    'elapsed_mins': elapsed_mins,
                }

            # 2. Waiting Queue (checked_in)
            # Queue Rules strictly applied:
            # 1. Emergency / queue_priority desc (Emergencies first)
            # 2. check_in_time asc (First-come, first-served)
            # 3. date_start asc
            waiting = doc_appts.filtered(lambda a: a.state == 'checked_in').sorted(
                key=lambda a: (
                    not a.is_emergency,
                    -(a.queue_priority or 0),
                    a.check_in_time or a.date_start or fields.Datetime.now(),
                    a.date_start or fields.Datetime.now()
                )
            )

            waiting_list = []
            for w_idx, w in enumerate(waiting):
                w_tok = clean_token(w, token_counter)
                token_counter += 1

                w_mins = 0
                if w.check_in_time:
                    diff = fields.Datetime.now() - w.check_in_time
                    w_mins = max(0, int(diff.total_seconds() / 60))

                waiting_list.append({
                    'id': w.id,
                    'token': w_tok,
                    'raw_token': w.token_number or w_tok,
                    'is_next': (w_idx == 0),
                    'patient_id': w.patient_id.id,
                    'patient_name': w.patient_id.name or 'Unknown',
                    'demographics': format_demographics(w.patient_id),
                    'treatment_name': w.treatment_id.name or w.reason or 'Consultation',
                    'waiting_mins': w_mins,
                    'is_emergency': bool(w.is_emergency or (w.queue_priority and w.queue_priority > 5)),
                })

            # 3. Upcoming Scheduled patients for this doctor today (confirmed/pending)
            upcoming = doc_appts.filtered(lambda a: a.state in ['confirmed', 'pending']).sorted(key=lambda a: a.date_start)
            upcoming_list = []
            for u in upcoming[:8]:
                u_tok = clean_token(u, token_counter)
                token_counter += 1
                start_utc = pytz.utc.localize(u.date_start)
                start_user = start_utc.astimezone(user_tz)
                time_display = start_user.strftime('%I:%M %p')

                upcoming_list.append({
                    'id': u.id,
                    'token': u_tok,
                    'patient_id': u.patient_id.id,
                    'patient_name': u.patient_id.name or 'Unknown',
                    'demographics': format_demographics(u.patient_id),
                    'scheduled_time': time_display,
                    'treatment_name': u.treatment_id.name or u.reason or 'Appointment',
                })

            doctors_data.append({
                'doctor_id': doc.id,
                'doctor_name': f"DR. {doc.name.upper()}" if not doc.name.upper().startswith("DR.") else doc.name.upper(),
                'specialization': spec,
                'operatory_title': op_label,
                'operatory_name': palette['name'],
                'accent_color': palette['color'],
                'bg_tint': palette['bg_tint'],
                'border_color': palette['border'],
                'avatar_url': f'/web/image?model=hr.employee&field=avatar_128&id={doc.id}',
                'now_serving': now_serving,
                'waiting_queue': waiting_list,
                'upcoming_list': upcoming_list,
                'waiting_count': len(waiting_list),
                'completed_count': len(doc_appts.filtered(lambda a: a.state == 'completed')),
                'total_doc_patients': len(doc_appts),
            })

        return {
            'clinic_name': clinic_name,
            'clinic_address': clinic_address,
            'stats': {
                'total_patients_today': total_patients_today,
                'now_serving_count': now_serving_total,
                'waiting_count': waiting_total,
                'completed_count': completed_total,
            },
            'doctors': doctors_data,
        }

    @api.model
    def get_dentist_dashboard_data(self, doctor_id=None, period='week'):
        """
        Fetches operational metrics, appointments overview chart data,
        doctors team profiles, and upcoming appointment schedule for the
        Dentist / Doctor Dashboard.
        """
        company = self.env.company
        today = fields.Date.today()
        user_tz = pytz.timezone(self.env.user.tz or 'Asia/Kolkata')
        now_local = datetime.now(user_tz)

        # Dynamic greeting
        hour = now_local.hour
        if hour < 12:
            greeting = "Good Morning"
        elif hour < 17:
            greeting = "Good Afternoon"
        else:
            greeting = "Good Evening"

        # Local day boundaries in UTC
        start_local = user_tz.localize(datetime.combine(today, time.min))
        end_local = user_tz.localize(datetime.combine(today, time.max))
        utc_start = start_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
        utc_end = end_local.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')

        # Current doctor / user
        selected_doctor = None
        if doctor_id:
            selected_doctor = self.env['hr.employee'].browse(int(doctor_id))
        else:
            # 1. Logged in user linked to active dentist
            emp = self.env['hr.employee'].search([
                ('user_id', '=', self.env.uid),
                ('is_dentist', '=', True),
                ('active', '=', True)
            ], limit=1)
            if not emp:
                # 2. Logged in user linked to any active employee
                emp = self.env['hr.employee'].search([
                    ('user_id', '=', self.env.uid),
                    ('active', '=', True)
                ], limit=1)
            if emp:
                selected_doctor = emp
            else:
                # 3. First active dentist in the clinic
                selected_doctor = self.env['hr.employee'].search([
                    ('is_dentist', '=', True),
                    ('active', '=', True)
                ], order='id asc', limit=1)

        doctor_name = selected_doctor.name if selected_doctor else (self.env.user.name or "Doctor")
        display_doctor_name = doctor_name.replace('Dr. ', '').strip()
        doctor_spec = selected_doctor.specialization if (selected_doctor and selected_doctor.specialization) else 'Dental Surgeon'

        # 1. Appointments Today - filtered to this doctor
        today_domain = [
            ('date_start', '>=', utc_start),
            ('date_start', '<=', utc_end),
        ]
        if selected_doctor:
            today_domain.append(('doctor_id', '=', selected_doctor.id))
        all_today_appts = self.search(today_domain, order='date_start asc')
        appointments_today_count = len(all_today_appts)

        # Treatments today (completed or procedures)
        treatments_today_count = sum(1 for a in all_today_appts if a.state == 'completed')

        # 2. New Patients Today
        new_patients_today = self.env['res.partner'].search_count([
            ('is_dental_patient', '=', True),
            ('create_date', '>=', utc_start),
            ('create_date', '<=', utc_end),
        ])

        # 3. Total Patients
        total_patients_count = self.env['res.partner'].search_count([
            ('is_dental_patient', '=', True),
        ])

        # 4. Total Revenue Today / This Month
        revenue_val = 0
        currency_symbol = company.currency_id.symbol if company.currency_id else '$'
        try:
            invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', today.replace(day=1))
            ])
            inv_sum = sum(invoices.mapped('amount_total'))
            if inv_sum > 0:
                revenue_val = int(inv_sum)
            else:
                completed_appts = all_today_appts.filtered(lambda a: a.state == 'completed')
                t_sum = sum(a.treatment_id.list_price for a in completed_appts if a.treatment_id)
                revenue_val = int(t_sum)
        except Exception:
            revenue_val = 0

        # 5. Upcoming Patients (for this doctor)
        up_dom = [
            ('date_start', '>=', utc_start),
            ('state', 'in', ['pending', 'confirmed', 'checked_in', 'in_consultation'])
        ]
        if selected_doctor:
            up_dom.append(('doctor_id', '=', selected_doctor.id))
        upcoming_patients_count = self.search_count(up_dom)

        # 6. Appointments Overview Chart Data (Week, Month, Year) - for this doctor
        start_of_week = today - timedelta(days=today.weekday())
        week_chart_days = []
        raw_counts = []
        for d in range(7):
            cur_d = start_of_week + timedelta(days=d)
            d_s = user_tz.localize(datetime.combine(cur_d, time.min)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
            d_e = user_tz.localize(datetime.combine(cur_d, time.max)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
            chart_dom = [('date_start', '>=', d_s), ('date_start', '<=', d_e)]
            if selected_doctor:
                chart_dom.append(('doctor_id', '=', selected_doctor.id))
            cnt = self.search_count(chart_dom)
            raw_counts.append((cur_d, cnt))

        max_week = max([c[1] for c in raw_counts] + [1])
        for cur_d, cnt in raw_counts:
            day_name = cur_d.strftime('%a')
            day_label = 'Sat' if day_name == 'Sat' else day_name
            pct = min(100, round((cnt / max_week) * 100, 1)) if max_week > 0 else 0
            week_chart_days.append({
                'label': day_label,
                'count': cnt,
                'height_pct': pct,
            })

        # Real Month Chart Data (Week 1 to Week 4 of current month)
        _, last_day_of_month = calendar.monthrange(today.year, today.month)
        month_intervals = [
            ('Week 1', 1, min(7, last_day_of_month)),
            ('Week 2', 8, min(14, last_day_of_month)),
            ('Week 3', 15, min(21, last_day_of_month)),
            ('Week 4', 22, last_day_of_month),
        ]
        month_counts = []
        for w_label, start_d, end_d in month_intervals:
            if start_d <= last_day_of_month:
                w_start = user_tz.localize(datetime(today.year, today.month, start_d, 0, 0, 0)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
                w_end = user_tz.localize(datetime(today.year, today.month, end_d, 23, 59, 59)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
                w_dom = [('date_start', '>=', w_start), ('date_start', '<=', w_end)]
                if selected_doctor:
                    w_dom.append(('doctor_id', '=', selected_doctor.id))
                w_cnt = self.search_count(w_dom)
            else:
                w_cnt = 0
            month_counts.append((w_label, w_cnt))

        max_month = max([c[1] for c in month_counts] + [1])
        month_chart_data = [{
            'label': w_label,
            'count': w_cnt,
            'height_pct': min(100, round((w_cnt / max_month) * 100, 1)) if max_month > 0 else 0
        } for w_label, w_cnt in month_counts]

        # Real Year Chart Data (Jan - Dec of current year)
        year_counts = []
        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        for m_idx, m_name in enumerate(month_names, 1):
            _, m_last_day = calendar.monthrange(today.year, m_idx)
            m_start = user_tz.localize(datetime(today.year, m_idx, 1, 0, 0, 0)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
            m_end = user_tz.localize(datetime(today.year, m_idx, m_last_day, 23, 59, 59)).astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S')
            y_dom = [('date_start', '>=', m_start), ('date_start', '<=', m_end)]
            if selected_doctor:
                y_dom.append(('doctor_id', '=', selected_doctor.id))
            y_cnt = self.search_count(y_dom)
            year_counts.append((m_name, y_cnt))

        max_year = max([c[1] for c in year_counts] + [1])
        year_chart_data = [{
            'label': m_name,
            'count': y_cnt,
            'height_pct': min(100, round((y_cnt / max_year) * 100, 1)) if max_year > 0 else 0
        } for m_name, y_cnt in year_counts]

        # 7. Doctor Profile & Info (Only this doctor on their page)
        avatar = f'/web/image?model=hr.employee&field=avatar_128&id={selected_doctor.id}' if selected_doctor else f'/web/image?model=res.users&field=avatar_128&id={self.env.uid}'

        doctors_list = []
        if selected_doctor:
            doctors_list.append({
                'id': selected_doctor.id,
                'name': display_doctor_name,
                'display_name': f"Dr. {display_doctor_name}",
                'specialization': doctor_spec,
                'avatar_url': avatar,
                'is_active': True,
                'today_appointments': appointments_today_count,
            })

        # 8. Upcoming Appointments List - filtered to this doctor
        upcoming_domain = [
            ('date_start', '>=', utc_start),
            ('date_start', '<=', utc_end),
        ]
        if selected_doctor:
            upcoming_domain.append(('doctor_id', '=', selected_doctor.id))

        appts_pool = self.search(upcoming_domain, order='date_start asc')
        upcoming_list = []
        for a in appts_pool:
            start_utc = pytz.utc.localize(a.date_start)
            start_user = start_utc.astimezone(user_tz)
            time_display = start_user.strftime('%I:%M %p').lstrip('0')

            treatment_title = 'Consultation'
            if a.treatment_id:
                tname = a.treatment_id.name
                if isinstance(tname, dict):
                    treatment_title = tname.get('en_US') or list(tname.values())[0]
                else:
                    treatment_title = str(tname)
                if 'Root Canal' in treatment_title:
                    treatment_title = 'Root Canal'
                elif 'Braces' in treatment_title:
                    treatment_title = 'Braces Checkup'

            if a.state == 'confirmed':
                status_label = 'Confirmed'
                status_color = 'color-confirmed'
            elif a.state == 'pending':
                status_label = 'Pending'
                status_color = 'color-pending'
            elif a.state in ['cancelled', 'refused']:
                status_label = 'Not Available'
                status_color = 'color-not-available'
            elif a.state == 'checked_in':
                status_label = 'Waiting'
                status_color = 'color-pending'
            elif a.state == 'in_consultation':
                status_label = 'In Consultation'
                status_color = 'color-confirmed'
            else:
                status_label = 'Confirmed'
                status_color = 'color-confirmed'

            doc_display_name = a.doctor_id.name.replace('Dr. ', '') if a.doctor_id else 'Doctor'

            upcoming_list.append({
                'id': a.id,
                'patient_id': a.patient_id.id,
                'patient_name': a.patient_id.name or 'Patient',
                'treatment': treatment_title,
                'doctor_id': a.doctor_id.id if a.doctor_id else False,
                'doctor_name': doc_display_name,
                'time': time_display,
                'status': a.state,
                'status_label': status_label,
                'status_color': status_color,
                'avatar_url': f'/web/image?model=res.partner&field=avatar_128&id={a.patient_id.id}',
            })

        waiting_count = len([a for a in all_today_appts if a.state in ['confirmed', 'checked_in', 'pending', 'in_consultation']])

        return {
            'doctor_info': {
                'id': selected_doctor.id if selected_doctor else False,
                'name': display_doctor_name,
                'display_name': f"Dr. {display_doctor_name}",
                'greeting': f"{greeting}, Dr. {display_doctor_name}",
                'subtitle': "Here's what's happening with your schedule today.",
                'specialization': doctor_spec,
                'avatar_url': avatar,
                'today_appointments': appointments_today_count,
                'completed_today': treatments_today_count,
                'waiting_today': waiting_count,
            },
            'kpi_stats': {
                'new_patients_today': new_patients_today,
                'appointments_today': appointments_today_count,
                'treatment_today': treatments_today_count,
                'total_revenue': f"{currency_symbol}{revenue_val:,}",
                'total_patients': f"{total_patients_count}",
                'upcoming_patients': upcoming_patients_count,
            },
            'overview_charts': {
                'week': week_chart_days,
                'month': month_chart_data,
                'year': year_chart_data,
            },
            'doctors': doctors_list,
            'upcoming_appointments': upcoming_list[:12],
        }

