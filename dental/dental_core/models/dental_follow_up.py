from odoo import models, fields, api


class DentalFollowUp(models.Model):
    _inherit = 'dental.follow.up'

    follow_up_type = fields.Selection([
        ('next_visit', 'Next Treatment Visit'),
        ('review', 'Post-Treatment Review'),
        ('general', 'General Follow-up'),
    ], string='Follow-up Type', default='general', tracking=True)
    case_id = fields.Many2one('dental.case', string='Dental Case', tracking=True, index=True, check_company=True)
    treatment_plan_id = fields.Many2one('dental.treatment.plan', string='Treatment Plan', check_company=True)
    plan_line_id = fields.Many2one('dental.treatment.plan.line', string='Treatment Plan Line', check_company=True)
    session_id = fields.Many2one('dental.treatment.session', string='Treatment Session', check_company=True)
    tooth_reference = fields.Char(string='Tooth Reference')

    @api.depends('appointment_id.company_id', 'case_id.company_id', 'session_id.company_id')
    def _compute_company_id(self):
        self._set_company_from('session_id', 'case_id', 'appointment_id')

    @api.model_create_multi
    def create(self, vals_list):
        # Follow-ups auto-created on appointment completion get linked to the consultation case
        for vals in vals_list:
            if vals.get('appointment_id') and not vals.get('case_id'):
                case = self.env['dental.appointment'].sudo().browse(vals['appointment_id']).case_id
                if case:
                    vals['case_id'] = case.id
        return super().create(vals_list)

    def action_book_followup_appointment(self):
        """Booked follow-ups continue the same dental case when the patient checks in."""
        action = super().action_book_followup_appointment()
        if self.case_id:
            action.setdefault('context', {})['default_case_id'] = self.case_id.id
        return action

    @api.onchange('case_id')
    def _onchange_case_id(self):
        case = self.case_id
        if not case:
            return
        if case.patient_id:
            self.patient_id = case.patient_id
        if not self.doctor_id and case.doctor_id:
            # Case doctor is hr.employee.public; follow-ups use hr.employee (same ids)
            self.doctor_id = self.env['hr.employee'].browse(case.doctor_id.id)
        if not self.appointment_id and case.current_visit_id:
            self.appointment_id = case.current_visit_id

    @api.onchange('plan_line_id')
    def _onchange_plan_line_id(self):
        line = self.plan_line_id
        if line:
            self.treatment_plan_id = line.plan_id
            self.treatment_id = line.treatment_id
            if line.tooth_reference:
                self.tooth_reference = line.tooth_reference
