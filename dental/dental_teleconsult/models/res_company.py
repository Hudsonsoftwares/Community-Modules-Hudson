# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    """Online consultation policy, set per clinic branch (each branch is a company)."""
    _inherit = 'res.company'

    dental_teleconsult_enabled = fields.Boolean(
        string='Online Video Consultations', default=True,
        help="Allow appointments of this branch to be held as online video consultations.")
    dental_teleconsult_require_prepayment = fields.Boolean(
        string='Pay Before Joining', default=True,
        help="Post the consultation fee invoice at confirmation; the patient can only enter the "
             "waiting room once it is paid (or the fee is waived).")
    dental_teleconsult_join_before = fields.Integer(
        string='Room Opens (Minutes Before)', default=15,
        help="How many minutes before the appointment start the patient may enter the waiting room.")
    dental_teleconsult_join_after = fields.Integer(
        string='Room Closes (Minutes After End)', default=30,
        help="How many minutes after the appointment end the join link stays valid.")
    dental_teleconsult_reminder_minutes = fields.Integer(
        string='Reminder (Minutes Before)', default=15,
        help="Send the patient a reminder with the join link this many minutes before the start. 0 disables it.")
    dental_teleconsult_verify_identity = fields.Boolean(
        string='Verify Patient Identity', default=True,
        help="Guests (patients not logged in to the portal) must confirm their date of birth, "
             "or the last 4 digits of their phone number, before entering.")
    dental_teleconsult_allow_recording = fields.Boolean(
        string='Allow Call Recording', default=False,
        help="Doctors may record online consultations when the patient has consented. "
             "Requires an Odoo SFU server configured in Discuss settings.")
