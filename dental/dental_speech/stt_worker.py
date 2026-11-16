"""Standalone faster-whisper worker, run in its own short-lived process by speech_engine.py.

Keeping Whisper out of the Odoo process means its memory (about 1-3 GB) never counts towards
Odoo's limit_memory_soft, and a native crash in the speech libraries cannot take the server down.

Protocol: audio bytes on stdin, JSON options as argv[1]; one JSON object on stdout.
Nothing is written to disk except the model files when they are first downloaded.
"""
import io
import json
import sys


def main():
    options = json.loads(sys.argv[1])
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return {'error': 'not_installed'}
    try:
        model = WhisperModel(options['model_size'], device='cpu', compute_type='int8',
                             download_root=options['model_dir'], local_files_only=options['offline'])
    except Exception as err:  # noqa: BLE001 - reported back to Odoo as text
        return {'error': 'model', 'detail': str(err)}
    if options.get('prepare_only'):
        return {'prepared': True}
    audio = sys.stdin.buffer.read()
    segments, info = model.transcribe(
        io.BytesIO(audio),
        language=options.get('language') or None,
        task=options.get('task') or 'transcribe',
        beam_size=5,
        vad_filter=True,
        initial_prompt=options.get('prompt') or None,
        condition_on_previous_text=False,
    )
    text = ' '.join(segment.text.strip() for segment in segments).strip()
    return {'text': text, 'duration': round(info.duration or 0.0, 1), 'language': info.language}


if __name__ == '__main__':
    try:
        result = main()
    except Exception as err:  # noqa: BLE001
        result = {'error': 'failed', 'detail': str(err)}
    sys.stdout.write(json.dumps(result))
    sys.stdout.flush()
