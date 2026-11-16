import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from ..models import llm_engine

_logger = logging.getLogger(__name__)

MAX_CONVERSATION_SECONDS = 30 * 60

# Where each approved section is saved: existing fields first, so current reports and history keep working
EXAMINATION_FIELDS = {
    'chief_complaint': 'chief_complaint',
    'symptoms': 'presenting_complaint',
    'clinical_findings': 'clinical_findings',
    'diagnosis': 'conversation_diagnosis',
    'treatment_plan': 'conversation_treatment_plan',
    'follow_up': 'conversation_follow_up',
}
CASE_FIELDS = {
    'medical_history': 'medical_history_summary',
}


def merge_text(existing, new):
    """Add the approved text below what is already recorded: never overwrite, never repeat."""
    existing, new = (existing or '').strip(), (new or '').strip()
    if not new or new in existing:
        return existing or False
    return '%s\n\n%s' % (existing, new) if existing else new


class DentalConversationSummaryWizard(models.TransientModel):
    """Record, transcribe and summarise a consultation for the doctor to review.

    Transient on purpose: the transcript and draft summary are not part of the patient record until
    the doctor approves them, and the draft is deleted as soon as it is approved or discarded.
    """
    _name = 'dental.conversation.summary.wizard'
    _description = 'Consultation Conversation Summary'

    state = fields.Selection([('record', 'Record'), ('review', 'Review')], default='record', required=True)
    case_id = fields.Many2one('dental.case', string='Case', required=True, readonly=True, ondelete='cascade')
    examination_id = fields.Many2one('dental.clinical.examination', string='Visit Consultation', readonly=True,
                                     ondelete='cascade',
                                     help="Consultation record of today's visit; created on approval if there is none yet.")
    patient_id = fields.Many2one(related='case_id.patient_id')

    patient_consent = fields.Boolean(
        string='Patient Consent to Record',
        help='The patient (or parent/guardian) was told that the conversation is recorded and transcribed on the '
             "clinic's own server, and agreed.")
    consent_date = fields.Datetime(string='Recording Started', readonly=True)
    audio_seconds = fields.Float(string='Recorded (seconds)', readonly=True, digits=(16, 0))
    transcript = fields.Text(string='Transcript')

    chief_complaint = fields.Text(string='Chief Complaint')
    symptoms = fields.Text(string='Symptoms')
    medical_history = fields.Text(string='Medical History')
    clinical_findings = fields.Text(string='Clinical Findings')
    diagnosis = fields.Text(string='Diagnosis (Doctor-Confirmed)')
    diagnosis_confirmed = fields.Boolean(string='I confirm this is my diagnosis')
    treatment_plan = fields.Text(string='Treatment Plan')
    follow_up = fields.Text(string='Follow-up')
    llm_model = fields.Char(string='Summarised By', readonly=True)
    keep_transcript = fields.Boolean(compute='_compute_keep_transcript')

    def _compute_keep_transcript(self):
        keep = self.env['ir.config_parameter'].sudo().get_bool('dental_speech.keep_transcript', False)
        self.keep_transcript = keep

    @api.model
    def _action_open(self, case, examination=None):
        return {
            'name': _('Consultation Conversation Summary'),
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_case_id': case.id,
                'default_examination_id': examination.id if examination else False,
            },
        }

    @api.model_create_multi
    def create(self, vals_list):
        context = self.env.context
        for vals in vals_list:
            # Readonly fields are not sent by the form: they arrive as context defaults
            case = self.env['dental.case'].browse(vals.get('case_id', context.get('default_case_id')))
            if not case:
                raise UserError(_("Save the consultation before recording the conversation."))
            case._dental_check_dictation_access()
            exam = self.env['dental.clinical.examination'].browse(
                vals.get('examination_id', context.get('default_examination_id')))
            if exam and exam.case_id != case:
                raise ValidationError(_("The visit consultation does not belong to this case."))
        return super().create(vals_list)

    def _check_open(self):
        self.ensure_one()
        self.case_id._dental_check_dictation_access()

    def _reopen(self):
        return {
            'name': _('Consultation Conversation Summary'),
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_transcribe_chunk(self, audio_b64, mime_type=None):
        """Transcribe one part of the conversation locally; the browser adds the text to the transcript."""
        self._check_open()
        if not self.patient_consent:
            raise UserError(_("Confirm the patient's consent before recording the conversation."))
        if self.state != 'record':
            raise UserError(_("Go back to recording before adding to the conversation."))
        if self.audio_seconds >= MAX_CONVERSATION_SECONDS:
            raise UserError(_("The conversation has reached the %s-minute limit.", MAX_CONVERSATION_SECONDS // 60))
        text, duration, language = self.case_id._dental_transcribe(audio_b64, mime_type)

        vals = {'audio_seconds': self.audio_seconds + duration}
        if not self.consent_date:
            vals['consent_date'] = fields.Datetime.now()
            # Audit without content, kept even if the recording is discarded later
            self.case_id.message_post(body=_(
                "Consultation conversation recording started; patient consent confirmed by %s. "
                "Audio is transcribed on this server and not stored.", self.env.user.name))
        self.write(vals)
        _logger.info('Dental conversation: user %s, case %s, %.1f s of audio transcribed',
                     self.env.user.id, self.case_id.id, duration)
        return {'text': text, 'duration': duration, 'language': language}

    def action_generate_summary(self):
        self._check_open()
        transcript = (self.transcript or '').strip()
        if not transcript:
            raise UserError(_("There is no transcript to summarise yet. Record the conversation or type it in."))
        params = self.env['ir.config_parameter'].sudo()
        model = params.get_str('dental_speech.llm_model', '') or llm_engine.DEFAULT_MODEL
        try:
            summary = llm_engine.summarize(
                transcript,
                endpoint=params.get_str('dental_speech.llm_endpoint', '') or llm_engine.DEFAULT_ENDPOINT,
                model=model,
                timeout=params.get_int('dental_speech.llm_timeout', 0) or llm_engine.DEFAULT_TIMEOUT,
            )
        except llm_engine.LLMUnavailable as err:
            _logger.warning('Dental summary unavailable: %s', err)
            raise UserError(_("The summary could not be generated: %s", err))
        except Exception:
            _logger.exception('Dental summary: generation failed')
            raise UserError(_("The summary could not be generated. Please try again."))

        # A suggested diagnosis always needs the doctor's explicit confirmation again
        self.write({**summary, 'state': 'review', 'diagnosis_confirmed': False, 'llm_model': model})
        _logger.info('Dental summary: user %s, case %s, model %s, %s characters summarised',
                     self.env.user.id, self.case_id.id, model, len(transcript))
        return self._reopen()

    def action_record_more(self):
        self._check_open()
        self.state = 'record'
        return self._reopen()

    def _get_examination(self):
        """Today's consultation record of this case; reuses the case's own find-or-create rule."""
        if self.examination_id:
            return self.examination_id
        Examination = self.env['dental.clinical.examination']
        if not self.case_id.current_visit_id:
            # Case without a visit: continue today's consultation instead of adding one per approval
            exam = Examination.search([
                ('case_id', '=', self.case_id.id), ('appointment_id', '=', False),
                ('examination_date', '>=', fields.Datetime.to_string(fields.Datetime.today())),
            ], order='examination_date desc, id desc', limit=1)
            if exam:
                return exam
        return Examination.browse(self.case_id.action_new_visit_consultation()['res_id'])

    def action_approve(self):
        self._check_open()
        if self.state != 'review':
            raise UserError(_("Generate and review the summary before approving it."))
        values = {key: (self[key] or '').strip() for key in llm_engine.SECTIONS}
        if not any(values.values()):
            raise UserError(_("The summary is empty. Add the consultation details or discard it."))
        if values['diagnosis'] and not self.diagnosis_confirmed:
            raise ValidationError(_(
                "Confirm the diagnosis before approving, or clear it. Only a diagnosis you have confirmed is saved."))

        case = self.case_id
        exam = self._get_examination()
        exam.check_access('write')
        now = fields.Datetime.now()
        exam_vals = {field: merge_text(exam[field], values[key]) for key, field in EXAMINATION_FIELDS.items()}
        exam_vals.update({'conversation_approved_by_id': self.env.user.id, 'conversation_approved_date': now})
        if self.consent_date:
            exam_vals.update({'conversation_consent_by_id': self.env.user.id, 'conversation_consent_date': self.consent_date})
        if self.keep_transcript and self.transcript:
            exam_vals['conversation_transcript'] = merge_text(exam.conversation_transcript, self.transcript)
        exam.write(exam_vals)

        case_vals = {field: merge_text(case[field], values[key]) for key, field in CASE_FIELDS.items() if values[key]}
        if not case.chief_complaint and values['chief_complaint']:
            case_vals['chief_complaint'] = values['chief_complaint']   # needed to complete the consultation
        if case_vals:
            case.write(case_vals)

        # Audit trail without patient content
        body = _("Consultation summary from the recorded conversation reviewed and approved by %(user)s "
                 "(generated locally by %(model)s). Transcript %(kept)s.",
                 user=self.env.user.name, model=self.llm_model or _('the local model'),
                 kept=_("kept in the consultation record") if exam_vals.get('conversation_transcript') else _("not stored"))
        exam.message_post(body=body)
        case.message_post(body=_("%(body)s Saved to %(exam)s.", body=body, exam=exam.name))
        _logger.info('Dental summary approved: user %s, case %s, examination %s', self.env.user.id, case.id, exam.id)

        self.unlink()   # the draft transcript is not kept outside the approved record
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _("Consultation summary approved and saved to %s.", exam.name),
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_discard(self):
        self.ensure_one()
        if self.consent_date:
            self.case_id.message_post(body=_(
                "Recorded consultation conversation discarded by %s; nothing was saved.", self.env.user.name))
        self.unlink()
        return {'type': 'ir.actions.act_window_close'}
