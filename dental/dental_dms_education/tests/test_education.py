# -*- coding: utf-8 -*-
import base64
import json
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

VIDEO = b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 64      # tiny fake MP4 payload


class EducationCommon:

    @classmethod
    def _setup_education(cls):
        env = cls.env
        env['dms.folder.rule'].sudo().search([('model_name', '=', 'hr.employee')]).write({'active': False})
        cls.env['res.lang']._activate_lang('fr_FR')
        cls.fr = env['res.lang']._lang_get('fr_FR')
        cls.en = env['res.lang']._lang_get('en_US')
        cls.patient = env['res.partner'].create({'name': 'Edu Patient Smith', 'is_dental_patient': True,
                                                 'phone': '9000000777', 'lang': 'fr_FR'})
        cls.manager = new_test_user(env, login='edu_manager', groups='base.group_user,dental_base.group_dental_manager')
        cls.dentist = new_test_user(env, login='edu_dentist', groups='base.group_user,dental_base.group_dental_dentist')
        cls.other_dentist = new_test_user(env, login='edu_dentist2', groups='base.group_user,dental_base.group_dental_dentist')
        cls.doctor = env['hr.employee'].create({'name': 'Dr Edu', 'dental_role': 'dentist'})
        cls.doctor.user_id = cls.dentist
        cls.root_canal = env.ref('dental_catalog.treatment_root_canal')
        cls.crown = env.ref('dental_catalog.treatment_crown')
        cls.case = env['dental.case'].create({'patient_id': cls.patient.id, 'doctor_id': cls.doctor.id,
                                              'chief_complaint': 'Pain'})
        cls.plan = env['dental.treatment.plan'].create({
            'patient_id': cls.patient.id, 'case_id': cls.case.id,
            'line_ids': [(0, 0, {'treatment_id': cls.root_canal.id, 'unit_price': 100})]})
        cls.rct_video = cls._add_media('RCT explained', 'dental_dms_education.topic_root_canal', 'pre_treatment', cls.en)
        cls.rct_video_fr = cls._add_media('RCT explique', 'dental_dms_education.topic_root_canal', 'pre_treatment',
                                          cls.fr, master=cls.rct_video)
        cls.rct_care = cls._add_media('After your RCT', 'dental_dms_education.topic_root_canal', 'post_care', cls.en)
        cls.crown_video = cls._add_media('Crowns', 'dental_dms_education.topic_crowns', 'pre_treatment', cls.en)

    @classmethod
    def _add_media(cls, name, topic_xmlid, purpose, lang, master=None):
        wizard = cls.env['dental.education.media.wizard'].with_user(cls.manager).create({
            'name': name, 'topic_id': cls.env.ref(topic_xmlid).id, 'media_type': 'video', 'purpose': purpose,
            'lang_id': lang.id, 'master_id': master.id if master else False,
            'file': base64.b64encode(VIDEO).decode(), 'file_name': 'clip.mp4'})
        action = wizard.action_add()
        return cls.env['dms.file'].browse(action['res_id'])


@tagged('post_install', '-at_install', 'dental_dms_education')
class TestEducation(EducationCommon, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_education()

    def test_media_stored_in_dms_library(self):
        media = self.rct_video.sudo()
        self.assertEqual(media.dental_doc_type, 'education')
        self.assertEqual(media.category_id, self.env.ref('dental_dms_education.topic_root_canal'))
        self.assertEqual(media.directory_id.parent_id.dental_doc_type, 'education')
        self.assertEqual(media.directory_id.dental_edu_topic_id, media.category_id)
        self.assertEqual(self.rct_video_fr.dental_edu_master_id, self.rct_video)

    def test_only_managers_add_media(self):
        wizard = self.env['dental.education.media.wizard'].with_user(self.manager).create({
            'name': 'x', 'topic_id': self.env.ref('dental_dms_education.topic_fillings').id,
            'lang_id': self.en.id, 'file': base64.b64encode(VIDEO).decode(), 'file_name': 'x.mp4'})
        with self.assertRaises(AccessError):
            wizard.with_user(self.dentist).action_add()

    def test_recommendations_language_and_purpose(self):
        action = self.plan.with_user(self.dentist).action_dental_educate_patient()
        session = self.env['dental.education.session'].browse(action['res_id'])
        self.assertEqual(session.purpose, 'pre_treatment')
        self.assertEqual(session.lang_id, self.fr, "defaults to the patient's language")
        self.assertEqual(session.line_ids.file_id, self.rct_video, 'root canal (pre-treatment) only')
        self.assertEqual(session.line_ids.play_file_id, self.rct_video_fr, 'French version played')

    def test_post_care_recommendation(self):
        session = self.env['dental.education.session'].create({
            'patient_id': self.patient.id, 'case_id': self.case.id, 'purpose': 'post_care'})
        session.action_load_recommendations()
        self.assertEqual(session.line_ids.file_id, self.rct_care)

    def test_dentist_can_browse_library_and_other_dentist_privacy(self):
        library = self.env['dms.file'].with_user(self.dentist).search([('dental_doc_type', '=', 'education')])
        self.assertIn(self.rct_video, library)
        session = self.env['dental.education.session'].with_user(self.dentist).create({
            'patient_id': self.patient.id, 'case_id': self.case.id})
        Session = self.env['dental.education.session']
        self.assertIn(session, Session.with_user(self.dentist).search([]))
        self.assertNotIn(session, Session.with_user(self.other_dentist).search([]),
                         "follows the case access of dental_core")

    def test_token_lifecycle_and_events(self):
        session = self.env['dental.education.session'].create({
            'patient_id': self.patient.id, 'case_id': self.case.id,
            'line_ids': [(0, 0, {'file_id': self.rct_video.id})]})
        session.action_share_tablet_link()
        token = session.sudo().access_token
        Session = self.env['dental.education.session']
        self.assertEqual(Session._get_by_token(session.id, token), session)
        self.assertFalse(Session._get_by_token(session.id, 'wrong'))
        line = session.line_ids
        res = session.sudo()._register_event(line, 'start', position=0, duration=60, device='tablet')
        session.sudo()._register_event(line, 'complete', position=60, duration=60, view_id=res['view_id'])
        self.assertTrue(line.completed)
        self.assertEqual(len(session.view_ids), 1)
        self.assertEqual(session.view_ids.device, 'tablet')
        self.assertEqual(session.view_ids.file_id, self.rct_video_fr)
        session.sudo()._register_event(False, 'ack', note='Will it hurt?')
        self.assertTrue(session.acknowledged)
        self.assertEqual(session.state, 'done')
        session.sudo().token_expiry = fields.Datetime.now() - timedelta(minutes=1)
        self.assertFalse(Session._get_by_token(session.id, token), 'expired links stop working')


@tagged('post_install', '-at_install', 'dental_dms_education')
class TestEducationHttp(EducationCommon, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_education()

    def test_presenter_routes(self):
        session = self.env['dental.education.session'].create({
            'patient_id': self.patient.id, 'case_id': self.case.id,
            'line_ids': [(0, 0, {'file_id': self.rct_video.id})]})
        session.action_share_tablet_link()
        token = session.sudo().access_token
        base = f'/dental/education/present/{session.id}/{token}'
        page = self.url_open(f'{base}?db={self.env.cr.dbname}')
        self.assertEqual(page.status_code, 200)
        self.assertIn('presenter.js', page.text)
        self.assertNotIn('Smith', page.text, 'only the first name is shown on clinic screens')
        line = session.line_ids
        media = self.url_open(f'{base}/media/{line.id}/{self.rct_video_fr.id}')
        self.assertEqual(media.status_code, 200)
        self.assertEqual(media.content, VIDEO)
        ranged = self.url_open(f'{base}/media/{line.id}/{self.rct_video_fr.id}', headers={'Range': 'bytes=0-9'})
        self.assertEqual(ranged.status_code, 206, 'video seeking needs HTTP range support')
        # media not in the playlist / wrong token
        self.assertEqual(self.url_open(f'{base}/media/{line.id}/{self.crown_video.id}').status_code, 404)
        self.assertEqual(self.url_open(f'/dental/education/present/{session.id}/nope').status_code, 404)
        # event logging through JSON-RPC
        res = self.url_open(f'{base}/event', data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': {
            'event': 'start', 'line_id': line.id, 'file_id': self.rct_video_fr.id, 'position': 0, 'duration': 60}}),
            headers={'Content-Type': 'application/json'})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['result']['ok'])
        self.assertEqual(len(session.view_ids), 1)

    def test_preview_requires_login(self):
        res = self.url_open(f'/dental/education/preview/{self.rct_video.id}', allow_redirects=False)
        self.assertIn(res.status_code, (303, 302, 401, 403))
        self.authenticate('edu_dentist', 'edu_dentist')
        res = self.url_open(f'/dental/education/preview/{self.rct_video.id}')
        self.assertEqual(res.status_code, 200)
        res = self.url_open(f'/dental/education/media/{self.rct_video.id}')
        self.assertEqual(res.content, VIDEO)
