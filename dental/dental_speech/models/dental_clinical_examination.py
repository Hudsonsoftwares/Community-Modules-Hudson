from odoo import models, fields

DOCTOR_GROUPS = 'dental_base.group_dental_dentist,dental_base.group_dental_manager'


class DentalClinicalExamination(models.Model):
    _inherit = 'dental.clinical.examination'

    # Sections of the approved conversation summary that have no field of their own yet.
    # Chief complaint, symptoms (presenting complaint) and clinical findings use the existing fields.
    conversation_diagnosis = fields.Text(
        string='Diagnosis (Doctor-Confirmed)',
        help='Diagnosis stated and confirmed by the doctor in the consultation. Record coded diagnoses in the '
             'Diagnoses tab of the case.')
    conversation_treatment_plan = fields.Text(string='Treatment Plan Notes')
    conversation_follow_up = fields.Text(string='Follow-up Instructions')
    conversation_transcript = fields.Text(
        string='Conversation Transcript', groups=DOCTOR_GROUPS, copy=False,
        help='Only kept when "Keep Approved Transcripts" is enabled in the settings.')

    conversation_consent_by_id = fields.Many2one('res.users', string='Recording Consent Confirmed By', readonly=True, copy=False)
    conversation_consent_date = fields.Datetime(string='Recording Consent Date', readonly=True, copy=False)
    conversation_approved_by_id = fields.Many2one('res.users', string='Summary Approved By', readonly=True, copy=False)
    conversation_approved_date = fields.Datetime(string='Summary Approved On', readonly=True, copy=False)

    def _prepare_carry_forward_vals(self):
        # The recorded conversation belongs to its own visit; a continued examination starts without it
        vals = super()._prepare_carry_forward_vals()
        return {key: value for key, value in vals.items() if not key.startswith('conversation_')}

    def action_open_conversation_summary(self):
        self.ensure_one()
        self.case_id._dental_check_dictation_access()
        return self.env['dental.conversation.summary.wizard']._action_open(self.case_id, examination=self)
