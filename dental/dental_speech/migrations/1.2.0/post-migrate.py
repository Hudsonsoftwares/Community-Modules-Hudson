from odoo.addons.dental_speech.models import speech_engine


def migrate(cr, version):
    """The dictation language was free text: convert it to a supported code, or automatic detection."""
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = 'dental_speech.language'")
    row = cr.fetchone()
    if not row:
        return
    code = speech_engine.normalize_language(row[0])
    if code:
        cr.execute("UPDATE ir_config_parameter SET value = %s WHERE key = 'dental_speech.language'", [code])
    else:
        cr.execute("DELETE FROM ir_config_parameter WHERE key = 'dental_speech.language'")
