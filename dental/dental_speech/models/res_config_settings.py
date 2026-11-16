from odoo import models, fields, _
from odoo.exceptions import AccessError

from . import llm_engine, speech_engine


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    dental_speech_model_size = fields.Selection([
        ('base', 'Base (fastest, basic accuracy)'),
        ('small', 'Small (recommended)'),
        ('medium', 'Medium (most accurate, slow on CPU)'),
    ], string='Dictation Model', default='small', config_parameter='dental_speech.model_size')
    dental_speech_language = fields.Selection(
        speech_engine.LANGUAGES, string='Dictation Language', config_parameter='dental_speech.language',
        help='Language the doctors speak. Choosing it makes recognition faster and more accurate than '
             'automatic detection. Leave empty to detect the language of each dictation.')
    dental_speech_translate = fields.Boolean(
        string='Write Notes in English', config_parameter='dental_speech.translate',
        help='Speech in any language (e.g. Malayalam or Hindi) is written into the notes as English text.')
    dental_speech_model_dir = fields.Char(
        string='Model Folder', config_parameter='dental_speech.model_dir',
        help="Folder holding the Whisper models. Leave empty to use Odoo's data folder.")
    dental_speech_offline = fields.Boolean(
        string='Offline Mode', config_parameter='dental_speech.offline',
        help='Never download models; only use models already present in the model folder.')
    dental_speech_llm_endpoint = fields.Char(
        string='Summary Model Address', config_parameter='dental_speech.llm_endpoint',
        default=llm_engine.DEFAULT_ENDPOINT,
        help='Ollama service on this server or on the clinic network. Public addresses are refused.')
    dental_speech_llm_model = fields.Char(
        string='Summary Model', config_parameter='dental_speech.llm_model', default=llm_engine.DEFAULT_MODEL,
        help='Ollama model used for consultation summaries, e.g. llama3.2:3b (fast on CPU) or llama3.1:8b.')
    dental_speech_llm_timeout = fields.Integer(
        string='Summary Time Limit (s)', config_parameter='dental_speech.llm_timeout',
        default=llm_engine.DEFAULT_TIMEOUT)
    dental_speech_keep_transcript = fields.Boolean(
        string='Keep Approved Transcripts', config_parameter='dental_speech.keep_transcript',
        help='Store the approved conversation transcript in the consultation record. '
             'When off, only the approved summary is kept.')

    def action_dental_speech_prepare_model(self):
        """Download the selected model in the background so the first dictation is fast."""
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_("Only administrators can download dictation models."))
        self.execute()  # save the chosen model/folder first
        params = self.env['ir.config_parameter'].sudo()
        speech_engine.prepare_model(
            model_size=params.get_str('dental_speech.model_size', 'small') or 'small',
            model_dir=params.get_str('dental_speech.model_dir', '') or None,
            offline=params.get_bool('dental_speech.offline', False),
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'info',
                'message': _("The dictation model is being downloaded in the background (about 500 MB for Small). "
                             "Dictation will be fast once it has finished."),
            },
        }

    def action_dental_speech_check_llm(self):
        """Check that the local summary model is running and installed, without sending patient data."""
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_("Only administrators can check the summary model."))
        self.execute()
        params = self.env['ir.config_parameter'].sudo()
        model = params.get_str('dental_speech.llm_model', '') or llm_engine.DEFAULT_MODEL
        try:
            installed = llm_engine.list_models(params.get_str('dental_speech.llm_endpoint', '') or llm_engine.DEFAULT_ENDPOINT)
        except llm_engine.LLMUnavailable as err:
            message, kind = _("The summary model cannot be reached: %s", err), 'danger'
        else:
            if model in installed or f'{model}:latest' in installed:
                message, kind = _("The summary model %s is installed and ready.", model), 'success'
            else:
                message, kind = _("The language model service is running, but %(model)s is not installed. "
                                  "On the server run: ollama pull %(model)s", model=model), 'warning'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'type': kind, 'message': message, 'sticky': kind != 'success'},
        }
