"""Local speech-to-text with faster-whisper (no paid API, no external upload).

Whisper runs in a separate short-lived process (stt_worker.py), never inside Odoo:
- its 1-3 GB of memory does not count towards Odoo's limit_memory_soft (exceeding it makes the
  threaded server restart, dropping every user's connection),
- a native crash in the speech libraries cannot take the Odoo server down,
- a hard timeout keeps each request well under Odoo's limit_time_real.
Audio is passed through a pipe in memory: recordings are never written to disk.
"""
import json
import logging
import os
import subprocess
import sys
import threading

from odoo.tools import config

_logger = logging.getLogger(__name__)

WORKER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'stt_worker.py')
TRANSCRIBE_TIMEOUT = 90      # seconds; Odoo kills requests after limit_time_real (120 s by default)
QUEUE_TIMEOUT = 20           # seconds to wait for a running dictation of another doctor
CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0

# Vocabulary hint: improves recognition of dental and drug terms in clinical dictation
DENTAL_PROMPT = (
    "Dental clinical notes. Tooth numbers, caries, pulpitis, periapical abscess, gingivitis, periodontitis, "
    "root canal treatment, pulpectomy, extraction, scaling, crown, bridge, implant, composite restoration, "
    "occlusal, mesial, distal, buccal, lingual, palatal, labial, IOPA, OPG, amoxicillin, metronidazole, "
    "ibuprofen, paracetamol, chlorhexidine."
)

# Dictation languages offered in the settings (Whisper language codes). Empty = automatic detection.
LANGUAGES = [
    ('en', 'English'),
    ('ml', 'Malayalam'),
    ('hi', 'Hindi'),
    ('ta', 'Tamil'),
    ('te', 'Telugu'),
    ('kn', 'Kannada'),
    ('mr', 'Marathi'),
    ('bn', 'Bengali'),
    ('gu', 'Gujarati'),
    ('pa', 'Punjabi'),
    ('ur', 'Urdu'),
    ('ar', 'Arabic'),
    ('fr', 'French'),
    ('de', 'German'),
    ('es', 'Spanish'),
]
LANGUAGE_NAMES = dict(LANGUAGES)

# Transcription is CPU heavy: one at a time keeps the clinic server responsive
_transcribe_slot = threading.BoundedSemaphore(1)


class SpeechEngineUnavailable(Exception):
    """The speech engine cannot be used (not installed, model missing, busy or too slow)."""


def default_model_dir():
    return os.path.join(config['data_dir'], 'dental_whisper_models')


def normalize_language(language):
    """Return a supported language code, or None for automatic detection.

    Accepts codes or names in any case ("EN", "english", "Malayalam"), so an older free-text
    setting can never make Whisper reject every dictation.
    """
    value = (language or '').strip().lower()
    if not value:
        return None
    if value in LANGUAGE_NAMES:
        return value
    for code, name in LANGUAGES:
        if value == name.lower():
            return code
    _logger.warning('Dental dictation: unsupported language "%s" in settings, using automatic detection', language)
    return None


def _options(model_size, language, model_dir, offline, prepare_only=False, translate=False):
    model_dir = model_dir or default_model_dir()
    os.makedirs(model_dir, exist_ok=True)
    return json.dumps({
        'model_size': model_size, 'language': normalize_language(language), 'model_dir': model_dir,
        'offline': bool(offline), 'prompt': DENTAL_PROMPT, 'prepare_only': prepare_only,
        'task': 'translate' if translate else 'transcribe',
    })


def transcribe(audio_bytes, model_size='small', language=None, model_dir=None, offline=False, translate=False):
    """Transcribe in-memory audio in a worker process. Returns (text, duration_seconds, language).

    With translate=True the speech, in any language, is written out as English text;
    the returned language is still the spoken one.
    """
    if not _transcribe_slot.acquire(timeout=QUEUE_TIMEOUT):
        raise SpeechEngineUnavailable('another dictation is being transcribed, please try again in a moment.')
    try:
        try:
            proc = subprocess.run(
                [sys.executable, WORKER, _options(model_size, language, model_dir, offline, translate=translate)],
                input=audio_bytes, capture_output=True, timeout=TRANSCRIBE_TIMEOUT,
                creationflags=CREATE_NO_WINDOW, check=False,
            )
        except subprocess.TimeoutExpired:
            raise SpeechEngineUnavailable(
                'the dictation took too long to transcribe; please dictate in shorter parts.') from None
    finally:
        _transcribe_slot.release()
    try:
        result = json.loads(proc.stdout or b'{}')
    except ValueError:
        result = {}
    if 'text' in result:
        return result['text'], result['duration'], result['language']
    error = result.get('error')
    _logger.warning('Dental dictation worker failed (exit %s): %s %s',
                    proc.returncode, result or '', (proc.stderr or b'')[-500:].decode(errors='replace'))
    if error == 'not_installed':
        raise SpeechEngineUnavailable('faster-whisper is not installed on the Odoo server.')
    if error == 'model':
        raise SpeechEngineUnavailable('the Whisper model "%s" could not be loaded (%s).' % (model_size, result.get('detail')))
    raise SpeechEngineUnavailable('the speech engine stopped unexpectedly.')


def prepare_model(model_size='small', model_dir=None, offline=False):
    """Download/verify the model in the background, so the first dictation does not have to wait."""
    subprocess.Popen(
        [sys.executable, WORKER, _options(model_size, None, model_dir, offline, prepare_only=True)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW, close_fds=True,
    )
