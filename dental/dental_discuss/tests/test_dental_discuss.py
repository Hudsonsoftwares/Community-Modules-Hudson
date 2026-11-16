# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'dental_discuss')
class TestDentalDiscuss(TransactionCase):
    """Unit and integration tests for Dental Hospital Discuss Workflows."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].create({'name': 'Dental Branch South'})

        # Users and Roles
        common_a = {'company_id': cls.company_a.id, 'company_ids': [cls.company_a.id]}
        common_b = {'company_id': cls.company_b.id, 'company_ids': [cls.company_b.id]}

        cls.user_dentist_1 = new_test_user(
            cls.env, login='dr_dentist_1',
            groups='base.group_user,dental_base.group_dental_dentist', **common_a
        )
        cls.user_dentist_2 = new_test_user(
            cls.env, login='dr_dentist_2',
            groups='base.group_user,dental_base.group_dental_dentist', **common_a
        )
        cls.user_specialist = new_test_user(
            cls.env, login='dr_specialist',
            groups='base.group_user,dental_base.group_dental_dentist,dental_second_opinion.group_dental_specialist', **common_a
        )
        cls.user_receptionist = new_test_user(
            cls.env, login='receptionist_1',
            groups='base.group_user,dental_base.group_dental_receptionist', **common_a
        )
        cls.user_pharmacist = new_test_user(
            cls.env, login='pharmacist_1',
            groups='base.group_user,dental_pharmacy.group_dental_pharmacist', **common_a
        )
        cls.user_lab_tech = new_test_user(
            cls.env, login='lab_tech_1',
            groups='base.group_user,dental_lab.group_dental_lab_user', **common_a
        )
        cls.user_manager = new_test_user(
            cls.env, login='clinic_manager_1',
            groups='base.group_user,dental_base.group_dental_manager', **common_a
        )
        cls.user_branch_b_dentist = new_test_user(
            cls.env, login='dr_branch_b',
            groups='base.group_user,dental_base.group_dental_dentist', **common_b
        )

        # Employees
        cls.doctor_emp_1 = cls.env['hr.employee'].create({
            'name': 'Dr. Alice Dentist',
            'dental_role': 'dentist',
            'user_id': cls.user_dentist_1.id,
            'company_id': cls.company_a.id,
        })
        cls.doctor_emp_2 = cls.env['hr.employee'].create({
            'name': 'Dr. Bob Endodontist',
            'dental_role': 'dentist',
            'user_id': cls.user_dentist_2.id,
            'company_id': cls.company_a.id,
        })
        cls.specialist_emp = cls.env['hr.employee'].create({
            'name': 'Dr. Sarah OralSurgeon',
            'dental_role': 'dentist',
            'user_id': cls.user_specialist.id,
            'company_id': cls.company_a.id,
        })
        cls.lab_tech_emp = cls.env['hr.employee'].create({
            'name': 'Tom Technician',
            'dental_role': 'lab_tech',
            'user_id': cls.user_lab_tech.id,
            'company_id': cls.company_a.id,
        })

        # Shared Patient
        cls.patient = cls.env['res.partner'].create({
            'name': 'John Doe (Patient)',
            'is_dental_patient': True,
            'phone': '9876543210',
            'allergies': 'Penicillin Allergy',
        })

    def test_01_channel_factory_and_department_channels(self):
        """Test channel factory helper and verify preconfigured channels exist."""
        # 1. Channel factory
        channel = self.env['discuss.channel'].get_or_create_dental_channel(
            channel_type='department',
            name='Test Orthodontics Group',
            partners=self.user_dentist_1.partner_id,
            company_id=self.company_a.id,
            is_phi=False,
            extra_vals={'dental_department': 'ortho'}
        )
        self.assertTrue(channel)
        self.assertEqual(channel.dental_channel_type, 'department')
        self.assertEqual(channel.dental_department, 'ortho')
        self.assertIn(self.user_dentist_1.partner_id, channel.channel_member_ids.mapped('partner_id'))

        # Idempotence: calling again retrieves the same channel
        same_channel = self.env['discuss.channel'].get_or_create_dental_channel(
            channel_type='department',
            name='Test Orthodontics Group',
            company_id=self.company_a.id,
            extra_vals={'dental_department': 'ortho'}
        )
        self.assertEqual(channel.id, same_channel.id)

    def test_02_dentist_to_dentist_peer_consultation(self):
        """Dentist opens clinical peer consultation wizard on dental case and starts Discuss channel."""
        # Create dental case as Dentist 1
        case = self.env['dental.case'].with_user(self.user_dentist_1).create({
            'patient_id': self.patient.id,
            'doctor_id': self.doctor_emp_1.id,
            'chief_complaint': 'Severe molar pain on chewing (tooth 46)',
            'company_id': self.company_a.id,
        })

        # Launch wizard to invite Dr. Bob (Dentist 2)
        wizard = self.env['dental.case.discuss.wizard'].with_user(self.user_dentist_1).create({
            'case_id': case.id,
            'patient_id': self.patient.id,
            'doctor_id': self.doctor_emp_1.id,
            'colleague_doctor_ids': [(4, self.doctor_emp_2.id)],
            'clinical_inquiry': 'Suspected cracked tooth syndrome vs apical periodontitis. Need second review.',
            'priority': 'urgent',
        })
        wizard.action_start_consultation()

        self.assertTrue(case.discuss_channel_id)
        self.assertEqual(case.discuss_channel_id.dental_channel_type, 'clinical')
        self.assertTrue(case.discuss_channel_id.is_confidential_phi)
        self.assertEqual(case.discuss_channel_count, 1)

        # Verify members
        member_partners = case.discuss_channel_id.channel_member_ids.mapped('partner_id')
        self.assertIn(self.user_dentist_1.partner_id, member_partners)
        self.assertIn(self.user_dentist_2.partner_id, member_partners)

        # Verify record chatter logged note
        messages = case.message_ids.mapped('body')
        self.assertTrue(any('Peer Consultation' in m for m in messages))

    def test_03_receptionist_to_doctor_coordination_and_checkin(self):
        """Receptionist checks in patient, dispatching alert and quick coordination to doctor."""
        start_time = datetime.now() + timedelta(hours=1)
        appt = self.env['dental.appointment'].with_user(self.user_receptionist).create({
            'patient_id': self.patient.id,
            'doctor_id': self.doctor_emp_1.id,
            'date_start': start_time,
            'date_end': start_time + timedelta(minutes=30),
            'branch_id': self.company_a.id,
        })
        appt.action_confirm()

        # Check-in triggers automated Discuss alert to doctor
        appt.action_check_in()
        self.assertEqual(appt.state, 'checked_in')
        self.assertTrue(appt.token_number)

        # Appointment chatter contains check-in alert
        appt_messages = appt.message_ids.mapped('body')
        self.assertTrue(any('Check-in Alert' in m for m in appt_messages))

        # Launch Reception Alert Wizard (e.g. Chair ready)
        alert_wizard = self.env['dental.reception.alert.wizard'].with_user(self.user_receptionist).create({
            'appointment_id': appt.id,
            'patient_id': self.patient.id,
            'doctor_id': self.doctor_emp_1.id,
            'alert_type': 'chair_ready',
            'operatory_room': 'Operatory 3 (Sterilized)',
            'priority': 'high',
            'notes': 'Patient escorted to chair 3.',
        })
        res = alert_wizard.action_send_alert()
        self.assertEqual(res['type'], 'ir.actions.client')

        # Check coordination channel was dispatched
        coord_channel = self.env['discuss.channel'].search([
            ('dental_channel_type', '=', 'coordination'),
            ('dental_department', '=', 'reception')
        ], limit=1)
        self.assertTrue(coord_channel)
        self.assertIn(self.user_dentist_1.partner_id, coord_channel.channel_member_ids.mapped('partner_id'))

    def test_04_lab_discussion_workflow(self):
        """Dentist or technician opens discuss channel on dental lab work order."""
        case = self.env['dental.case'].with_user(self.user_dentist_1).create({
            'patient_id': self.patient.id,
            'doctor_id': self.doctor_emp_1.id,
            'company_id': self.company_a.id,
        })
        lab_order = self.env['dental.lab.order'].with_user(self.user_dentist_1).create({
            'patient_id': self.patient.id,
            'dentist_id': self.doctor_emp_1.id,
            'technician_id': self.user_lab_tech.id,
            'case_id': case.id,
            'company_id': self.company_a.id,
            'due_date': fields.Date.today() + timedelta(days=5),
        })

        lab_order.action_open_lab_channel()
        self.assertTrue(lab_order.discuss_channel_id)
        self.assertEqual(lab_order.discuss_channel_id.dental_channel_type, 'lab')
        self.assertEqual(lab_order.discuss_channel_count, 1)

        members = lab_order.discuss_channel_id.channel_member_ids.mapped('partner_id')
        self.assertIn(self.user_dentist_1.partner_id, members)
        self.assertIn(self.user_lab_tech.partner_id, members)

    def test_05_pharmacy_discussion_workflow(self):
        """Dentist and pharmacist discuss medication instructions on dental prescription."""
        case = self.env['dental.case'].with_user(self.user_dentist_1).create({
            'patient_id': self.patient.id,
            'doctor_id': self.doctor_emp_1.id,
            'company_id': self.company_a.id,
        })
        rx = self.env['dental.prescription'].with_user(self.user_dentist_1).create({
            'patient_id': self.patient.id,
            'dentist_id': self.doctor_emp_1.id,
            'case_id': case.id,
            'company_id': self.company_a.id,
        })

        rx.action_open_pharmacy_channel()
        self.assertTrue(rx.discuss_channel_id)
        self.assertEqual(rx.discuss_channel_id.dental_channel_type, 'pharmacy')
        self.assertEqual(rx.discuss_channel_count, 1)

        members = rx.discuss_channel_id.channel_member_ids.mapped('partner_id')
        self.assertIn(self.user_dentist_1.partner_id, members)

    def test_06_specialist_referral_workflow(self):
        """Submitting a second opinion request creates a referral Discuss channel."""
        case = self.env['dental.case'].with_user(self.user_dentist_1).create({
            'patient_id': self.patient.id,
            'doctor_id': self.doctor_emp_1.id,
            'company_id': self.company_a.id,
        })
        ref = self.env['dental.second.opinion'].with_user(self.user_dentist_1).create({
            'case_id': case.id,
            'requesting_doctor_id': self.doctor_emp_1.id,
            'specialist_id': self.specialist_emp.id,
            'clinical_question': 'Evaluate for surgical bone augmentation and implant feasibility.',
            'company_id': self.company_a.id,
        })

        # Submitting referral automatically initializes referral chat
        ref.action_submit()
        self.assertTrue(ref.discuss_channel_id)
        self.assertEqual(ref.discuss_channel_id.dental_channel_type, 'referral')
        self.assertEqual(ref.discuss_channel_count, 1)

        members = ref.discuss_channel_id.channel_member_ids.mapped('partner_id')
        self.assertIn(self.user_dentist_1.partner_id, members)
        self.assertIn(self.user_specialist.partner_id, members)

    def test_07_log_chatter_wizard(self):
        """Use dental.log.chatter.wizard to write formal consensus into record chatter."""
        case = self.env['dental.case'].with_user(self.user_dentist_1).create({
            'patient_id': self.patient.id,
            'doctor_id': self.doctor_emp_1.id,
            'company_id': self.company_a.id,
        })
        channel = self.env['discuss.channel'].create({
            'name': 'Case Consensus Channel',
            'channel_type': 'group',
            'dental_channel_type': 'clinical',
            'dental_case_id': case.id,
            'dental_patient_id': self.patient.id,
            'company_id': self.company_a.id,
        })
        channel._add_members(users=self.user_dentist_1)

        wizard = self.env['dental.log.chatter.wizard'].with_user(self.user_dentist_1).create({
            'channel_id': channel.id,
            'case_id': case.id,
            'patient_id': self.patient.id,
            'log_type': 'clinical_decision',
            'decision_summary': 'Consensus reached: Proceed with endodontic retreatment followed by zirconia crown.',
            'action_plan': '1. Schedule 60-min session with Dr. Bob. 2. Prescribe post-op analgesics.',
        })
        wizard.action_log_to_chatter()

        # Check chatter has the consensus
        messages = case.message_ids.mapped('body')
        self.assertTrue(any('Consensus reached' in m for m in messages))
        self.assertTrue(any('agreed action plan' in m.lower() for m in messages))

    def test_08_multi_company_channel_isolation(self):
        """Branch A discuss channels must stay isolated from Branch B users."""
        channel_a = self.env['discuss.channel'].with_company(self.company_a).create({
            'name': 'Branch A Private Clinical Chat',
            'channel_type': 'channel',
            'dental_channel_type': 'clinical',
            'company_id': self.company_a.id,
            'is_confidential_phi': True,
        })

        # Branch B dentist should NOT see channel_a
        channels_visible_to_b = self.env['discuss.channel'].with_user(self.user_branch_b_dentist).with_company(self.company_b).search([
            ('id', '=', channel_a.id)
        ])
        self.assertFalse(channels_visible_to_b)
