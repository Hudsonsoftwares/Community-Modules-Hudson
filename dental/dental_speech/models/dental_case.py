import base64
import binascii
import logging

from odoo import models, _
from odoo.exceptions import AccessError, UserError

from . import speech_engine

_logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 10 * 1024 * 1024        # far above a 2-minute browser Opus recording (about 1 MB)
ALLOWED_MIME_TYPES = {
    'audio/webm', 'video/webm', 'audio/ogg', 'audio/mp4', 'audio/mpeg', 'audio/wav', 'audio/x-wav', 'audio/aac',
}
DICTATION_GROUPS = ('dental_base.group_dental_dentist', 'dental_base.group_dental_manager')


class DentalCase(models.Model):
    _inherit = 'dental.case'

    def _dental_check_dictation_access(self):
        """Doctors and managers only, on cases they may edit and that are still open."""
        user = self.env.user
        if not any(user.has_group(group) for group in DICTATION_GROUPS):
            raise AccessError(_("Only doctors and clinic managers can use voice dictation."))
        if self:
            self.ensure_one()
            self.check_access('write')     # own cases / own branch only, like editing the notes
            if self.state in ('completed', 'cancelled'):
                raise UserError(_("Clinical notes of a completed or cancelled case cannot be changed."))
        else:
            self.check_access('create')

    def _dental_transcribe(self, audio_b64, mime_type=None):
        """Validate and transcribe in-memory audio locally. Returns (text, duration, language); stores nothing."""
        mime = (mime_type or '').split(';')[0].strip().lower()
        if mime and mime not in ALLOWED_MIME_TYPES:
            raise UserError(_("Unsupported audio format: %s", mime))
        if not audio_b64 or len(audio_b64) > MAX_AUDIO_BYTES * 4 // 3 + 4:
            raise UserError(_("The recording is empty or too long. Please dictate in shorter parts."))
        try:
            audio = base64.b64decode(audio_b64, validate=True)
        except (binascii.Error, ValueError):
            raise UserError(_("The recording could not be read. Please try again."))

        params = self.env['ir.config_parameter'].sudo()
        try:
            return speech_engine.transcribe(
                audio,
                model_size=params.get_str('dental_speech.model_size', 'small') or 'small',
                language=params.get_str('dental_speech.language', '') or None,
                model_dir=params.get_str('dental_speech.model_dir', '') or None,
                offline=params.get_bool('dental_speech.offline', False),
                translate=params.get_bool('dental_speech.translate', False),
            )
        except speech_engine.SpeechEngineUnavailable as err:
            _logger.warning('Dental dictation unavailable: %s', err)
            raise UserError(_("Voice dictation could not be completed: %s", err))
        except Exception:
            _logger.exception('Dental dictation: transcription failed')
            raise UserError(_("The recording could not be transcribed. Please try again."))

    def dental_transcribe_audio(self, audio_b64, mime_type=None):
        """Transcribe a dictation recorded in the consultation form, locally on this server.

        Called on the open case (or on an empty recordset for a case not saved yet). Returns the text
        for the doctor to review; nothing is stored until the doctor inserts it and saves the form.
        """
        self._dental_check_dictation_access()
        text, duration, language = self._dental_transcribe(audio_b64, mime_type)

        # Audit trail without patient content: neither the audio nor the text is logged
        _logger.info('Dental dictation: user %s, case %s, %.1f s of audio', self.env.user.id, self.id or 'new', duration)
        if self:
            self.message_post(body=_("Voice dictation transcribed locally (%(seconds)s s of audio).", seconds=duration))
        return {
            'text': text, 'duration': duration, 'language': language,
            'language_name': speech_engine.LANGUAGE_NAMES.get(language, language or ''),
            'translated': self.env['ir.config_parameter'].sudo().get_bool('dental_speech.translate', False),
        }

    def action_open_conversation_summary(self):
        """Record the doctor-patient conversation of today's visit and summarise it for review."""
        self.ensure_one()
        self._dental_check_dictation_access()
        if self.state in ('completed', 'cancelled'):
            raise UserError(_("Reopen the case before recording a new conversation summary."))
        return self.env['dental.conversation.summary.wizard']._action_open(self)
