{
    'name': 'Dental Voice Dictation',
    'version': '1.2.0',
    'category': 'Healthcare/Dental',
    'summary': 'Free, local Whisper dictation and doctor-approved consultation summaries',
    'author': 'Hudson Software Solutions',
    'description': """
Dental Voice Dictation
======================
Doctors dictate clinical notes in the consultation form. Audio is transcribed on the Odoo
server with faster-whisper (open source): no paid API, no upload to external services,
and recordings are processed in memory only, never stored.

Consultation Conversation Summary: with the patient's consent, the doctor records the
consultation; it is transcribed locally and summarised by a local language model (Ollama)
into Chief Complaint, Symptoms, Medical History, Clinical Findings, Diagnosis
(doctor-confirmed only), Treatment Plan and Follow-up. The doctor edits and approves the
summary before anything is saved to today's visit consultation record.

Requires on the server (see requirements.txt; av must stay pinned):
    python -m pip install faster-whisper==1.2.1 av==14.2.0
and, for summaries, Ollama (https://ollama.com) with a model, e.g.:
    ollama pull llama3.2:3b
    """,
    'depends': ['dental_core'],
    'data': [
        'security/ir.access.csv',
        'views/dental_case_views.xml',
        'views/dental_clinical_examination_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/conversation_summary_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'dental_speech/static/src/dictation_field.js',
            'dental_speech/static/src/dictation_field.xml',
            'dental_speech/static/src/dictation_field.scss',
            'dental_speech/static/src/conversation_recorder.js',
            'dental_speech/static/src/conversation_recorder.xml',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
