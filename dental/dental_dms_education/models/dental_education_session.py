# -*- coding: utf-8 -*-
import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import consteq

SESSION_PURPOSES = [
    ('pre_treatment', 'Before Treatment'),
    ('post_care', 'Post-Treatment Care'),
    ('general', 'General Education'),
]
# Which media purposes fit which kind of session
PURPOSE_MATCH = {
    'pre_treatment': ('pre_treatment', 'procedure'),
    'post_care': ('post_care',),
    'general': ('pre_treatment', 'procedure', 'post_care', 'general'),
}
DEFAULT_LINK_HOURS = 12


class DentalEducationSession(models.Model):
    """Patient education record: the media chosen for a patient, presented and acknowledged."""
    _name = 'dental.education.session'
    _description = 'Patient Education Session'
    _inherit = ['mail.thread', 'dental.company.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    patient_id = fields.Many2one('res.partner', string='Patient', required=True, index=True, tracking=True,
                                 domain=[('is_dental_patient', '=', True)])
    case_id = fields.Many2one('dental.case', string='Dental Case', index=True, check_company=True)
    examination_id = fields.Many2one('dental.clinical.examination', string='Consultation', index=True,
                                     check_company=True)
    treatment_plan_id = fields.Many2one('dental.treatment.plan', string='Treatment Plan', index=True,
                                        check_company=True)
    treatment_session_id = fields.Many2one('dental.treatment.session', string='Treatment Session', index=True,
                                           check_company=True)
    appointment_id = fields.Many2one('dental.appointment', string='Appointment', index=True, check_company=True)
    user_id = fields.Many2one('res.users', string='Presented By', default=lambda self: self.env.user, tracking=True)
    purpose = fields.Selection(SESSION_PURPOSES, string='Purpose', required=True, default='pre_treatment',
                               tracking=True)
    lang_id = fields.Many2one('res.lang', string='Language', compute='_compute_lang_id', store=True,
                              readonly=False, help="Defaults to the patient's language.")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('presented', 'Presented'),
        ('done', 'Completed'),
        ('cancel', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)
    line_ids = fields.One2many('dental.education.session.line', 'session_id', string='Playlist', copy=True)
    view_ids = fields.One2many('dental.education.view', 'session_id', string='Viewing History', readonly=True)
    view_count = fields.Integer(compute='_compute_progress', string='Views')
    completed_count = fields.Integer(compute='_compute_progress', string='Completed Media')
    progress = fields.Float(compute='_compute_progress', string='Progress (%)')
    notes = fields.Html(string='Dentist Notes')

    access_token = fields.Char(copy=False, groups='base.group_user')
    token_expiry = fields.Datetime(string='Screen Link Valid Until', copy=False, readonly=True)
    presenter_url = fields.Char(string='Screen / Tablet Link', compute='_compute_presenter_url')
    presenter_qr_html = fields.Html(string='Tablet QR Code', compute='_compute_presenter_url', sanitize=False)

    acknowledged = fields.Boolean(string='Patient Acknowledged', readonly=True, copy=False, tracking=True)
    acknowledged_date = fields.Datetime(string='Acknowledged On', readonly=True, copy=False)
    acknowledgement_note = fields.Text(string='Patient Questions / Feedback', readonly=True, copy=False)

    @api.depends('case_id.company_id', 'examination_id.company_id', 'treatment_plan_id.company_id',
                 'appointment_id.company_id')
    def _compute_company_id(self):
        self._set_company_from('examination_id', 'case_id', 'treatment_plan_id', 'treatment_session_id',
                               'appointment_id')

    @api.depends('patient_id')
    def _compute_lang_id(self):
        Lang = self.env['res.lang']
        for session in self:
            if session.lang_id:
                continue
            code = session.patient_id.lang or self.env.user.lang
            session.lang_id = Lang._lang_get(code) if code else False

    @api.depends('line_ids.completed', 'view_ids')
    def _compute_progress(self):
        for session in self:
            total = len(session.line_ids)
            done = len(session.line_ids.filtered('completed'))
            session.completed_count = done
            session.view_count = len(session.view_ids)
            session.progress = (100.0 * done / total) if total else 0.0

    @api.depends('access_token', 'token_expiry')
    def _compute_presenter_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for session in self:
            token = session.sudo().access_token
            if token and session.id:
                url = f'{base}/dental/education/present/{session.id}/{token}?db={self.env.cr.dbname}'
                session.presenter_url = url
                session.presenter_qr_html = (
                    f'<img alt="QR" style="width:180px;height:180px" '
                    f'src="/report/barcode/?barcode_type=QR&amp;width=360&amp;height=360&amp;value='
                    f'{self._url_quote(url)}"/>')
            else:
                session.presenter_url = False
                session.presenter_qr_html = False

    @staticmethod
    def _url_quote(value):
        from urllib.parse import quote
        return quote(value, safe='')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('dental.education.session') or _('New')
        return super().create(vals_list)

    # ------------------------------------------------------------------ recommendations
    def _recommendation_products(self):
        """Dental treatments the session is about."""
        self.ensure_one()
        products = self.env['product.template']
        plans = self.treatment_plan_id
        if self.case_id:
            plans |= self.env['dental.treatment.plan'].search([('case_id', '=', self.case_id.id)])
        if self.examination_id.case_id:
            plans |= self.env['dental.treatment.plan'].search([('case_id', '=', self.examination_id.case_id.id)])
        products |= plans.line_ids.treatment_id
        if self.treatment_session_id:
            # post-care: the treatment actually performed in this session
            products |= self.treatment_session_id.plan_line_id.treatment_id \
                or self.treatment_session_id.plan_id.line_ids.treatment_id
        return products

    @api.model
    def _recommend_media(self, products, purpose, company, lang_code, limit=12):
        """Rank published library media for the given treatments. Returns dms.file records (originals)."""
        domain = [('dental_doc_type', '=', 'education'), ('dental_edu_master_id', '=', False),
                  ('dental_edu_published', '=', True), ('company_id', 'in', [company.id, False])]
        purposes = PURPOSE_MATCH.get(purpose, PURPOSE_MATCH['general'])
        candidates = self.env['dms.file'].search(domain)
        categories = products.mapped('dental_treatment_category_id')
        scored = []
        for media in candidates:
            if media.dental_edu_purpose and media.dental_edu_purpose not in purposes:
                continue
            topic = media.category_id
            score = 0
            if media.dental_edu_product_ids & products:
                score += 5
            if topic.dental_product_ids & products:
                score += 3
            if topic.dental_treatment_category_ids & categories:
                score += 1
            if not products and media.dental_edu_purpose == 'general':
                score += 1
            if score:
                if lang_code and lang_code in media._dental_edu_family().mapped('dental_edu_lang_id.code'):
                    score += 0.5
                scored.append((score, media.id, media))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return self.env['dms.file'].union(*[media for _score, _id, media in scored[:limit]])

    def action_load_recommendations(self):
        for session in self:
            media = self._recommend_media(session._recommendation_products(), session.purpose, session.company_id,
                                          session.lang_id.code)
            existing = session.line_ids.file_id
            start = max(session.line_ids.mapped('sequence') or [0])
            session.write({'line_ids': [
                (0, 0, {'file_id': m.id, 'sequence': start + 10 * (i + 1), 'recommended': True})
                for i, m in enumerate(media - existing)]})
        return True

    # ------------------------------------------------------------------ presentation
    def _ensure_token(self, renew=False):
        hours = int(self.env['ir.config_parameter'].sudo().get_param('dental_dms_education.link_hours',
                                                                     DEFAULT_LINK_HOURS) or DEFAULT_LINK_HOURS)
        for session in self.sudo():
            if renew or not session.access_token or not session.token_expiry \
                    or session.token_expiry < fields.Datetime.now():
                session.write({'access_token': secrets.token_urlsafe(32),
                               'token_expiry': fields.Datetime.now() + timedelta(hours=hours)})

    def _check_presentable(self):
        for session in self:
            if session.state == 'cancel':
                raise UserError(_('A cancelled session cannot be presented.'))
            if not session.line_ids:
                raise UserError(_('Add at least one video or media to the playlist first.'))

    def action_present(self):
        """Open the full-screen player (clinic monitor) in a new browser tab."""
        self.ensure_one()
        self.check_access('write')
        self._check_presentable()
        self._ensure_token()
        if self.state == 'draft':
            self.state = 'presented'
        return {'type': 'ir.actions.act_url', 'url': self.presenter_url, 'target': 'new'}

    def action_share_tablet_link(self):
        """Generate (or renew) the expiring link / QR code to open the playlist on a tablet."""
        self.ensure_one()
        self.check_access('write')
        self._check_presentable()
        self._ensure_token(renew=True)
        if self.state == 'draft':
            self.state = 'presented'
        return True

    def action_revoke_link(self):
        self.check_access('write')
        self.sudo().write({'access_token': False, 'token_expiry': False})
        return True

    def action_done(self):
        self.write({'state': 'done'})
        self.sudo().write({'access_token': False, 'token_expiry': False})

    def action_cancel(self):
        self.write({'state': 'cancel'})
        self.sudo().write({'access_token': False, 'token_expiry': False})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_open_library(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('dental_dms_education.action_dental_education_library')
        action['context'] = {'dental_edu_session_id': self.id}
        return action

    @api.model
    def _get_by_token(self, session_id, token):
        """Session for a public presenter link, or empty recordset (expired / revoked / wrong token)."""
        session = self.sudo().browse(session_id).exists()
        if not session or not token or not session.access_token or not consteq(session.access_token, token):
            return self.browse()
        if session.state == 'cancel' or not session.token_expiry or session.token_expiry < fields.Datetime.now():
            return self.browse()
        return session

    def _register_event(self, line, event, position=0.0, duration=0.0, view_id=None, device=None, variant=None,
                        note=None):
        """Record a player event coming from the clinic screen (called in sudo with a validated token)."""
        self.ensure_one()
        View = self.env['dental.education.view'].sudo()
        now = fields.Datetime.now()
        if event == 'ack':
            self.write({'acknowledged': True, 'acknowledged_date': now,
                        'acknowledgement_note': (note or '')[:2000] or False, 'state': 'done'})
            self.message_post(body=_('The patient confirmed having watched and understood the education media.'))
            return {'ok': True}
        if not line or line.session_id != self:
            return {'ok': False}
        media = variant if variant and variant in line.file_id._dental_edu_family() else line.play_file_id
        view = View.browse(int(view_id)).exists() if view_id else View
        if view and (view.session_id != self or view.line_id != line):
            view = View
        position = max(0.0, float(position or 0.0))
        duration = max(0.0, float(duration or 0.0))
        if not view:
            view = View.create({
                'session_id': self.id, 'line_id': line.id, 'file_id': media.id, 'date_start': now,
                'device': device if device in dict(View._fields['device'].selection) else 'screen',
            })
        vals = {'date_end': now, 'watched_seconds': max(view.watched_seconds, position)}
        if duration:
            vals['media_duration'] = duration
        if event == 'complete':
            vals['completed'] = True
        view.write(vals)
        line_vals = {'last_viewed': now, 'watched_seconds': max(line.watched_seconds, position)}
        if event == 'complete':
            line_vals['completed'] = True
        line.write(line_vals)
        if self.state == 'draft':
            self.state = 'presented'
        return {'ok': True, 'view_id': view.id}


class DentalEducationSessionLine(models.Model):
    _name = 'dental.education.session.line'
    _description = 'Patient Education Playlist Item'
    _order = 'sequence, id'

    session_id = fields.Many2one('dental.education.session', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='session_id.company_id', store=True, index=True)
    sequence = fields.Integer(default=10)
    file_id = fields.Many2one('dms.file', string='Media', required=True, ondelete='cascade',
                              domain="[('dental_doc_type', '=', 'education'), ('dental_edu_master_id', '=', False),"
                                     " ('dental_edu_published', '=', True)]")
    play_file_id = fields.Many2one('dms.file', string='Version Played', compute='_compute_play_file_id',
                                   help="Language version matching the session language.")
    play_lang_id = fields.Many2one('res.lang', string='Played In', compute='_compute_play_file_id')
    media_type = fields.Selection(related='file_id.dental_edu_media_type')
    media_purpose = fields.Selection(related='file_id.dental_edu_purpose')
    topic_id = fields.Many2one(related='file_id.category_id', string='Topic')
    thumbnail = fields.Image(related='file_id.image_1920', string='Thumbnail')
    recommended = fields.Boolean(string='Recommended', readonly=True)
    watched_seconds = fields.Float(string='Watched (s)', readonly=True)
    completed = fields.Boolean(readonly=True)
    last_viewed = fields.Datetime(readonly=True)

    @api.depends('file_id', 'session_id.lang_id')
    def _compute_play_file_id(self):
        for line in self:
            media = line.file_id._dental_edu_for_lang(line.session_id.lang_id.code) if line.file_id else False
            line.play_file_id = media
            line.play_lang_id = media.dental_edu_lang_id if media else False

    def action_preview(self):
        self.ensure_one()
        return self.play_file_id.action_dental_edu_preview()


class DentalEducationView(models.Model):
    """Viewing history: one row per playback of a media on a clinic screen."""
    _name = 'dental.education.view'
    _description = 'Patient Education Viewing History'
    _order = 'date_start desc, id desc'

    session_id = fields.Many2one('dental.education.session', required=True, ondelete='cascade', index=True)
    line_id = fields.Many2one('dental.education.session.line', ondelete='set null', index=True)
    file_id = fields.Many2one('dms.file', string='Media', ondelete='set null', index=True)
    lang_id = fields.Many2one(related='file_id.dental_edu_lang_id', string='Language', store=True)
    topic_id = fields.Many2one(related='file_id.category_id', string='Topic', store=True)
    patient_id = fields.Many2one(related='session_id.patient_id', store=True, index=True)
    company_id = fields.Many2one(related='session_id.company_id', store=True, index=True)
    presented_by_id = fields.Many2one(related='session_id.user_id', store=True, string='Presented By')
    date_start = fields.Datetime(string='Started', required=True, default=fields.Datetime.now)
    date_end = fields.Datetime(string='Last Activity')
    watched_seconds = fields.Float(string='Watched (s)')
    media_duration = fields.Float(string='Duration (s)')
    completed = fields.Boolean()
    device = fields.Selection([('screen', 'Clinic Monitor'), ('tablet', 'Tablet'), ('desktop', 'Desktop')],
                              default='screen')
