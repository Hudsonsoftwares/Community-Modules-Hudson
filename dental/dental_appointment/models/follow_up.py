from datetime import timedelta
from odoo import models, fields, api, _

class DentalFollowUp(models.Model):
    _name = 'dental.follow.up'
    _description = 'Dental Follow-up'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date asc, id desc'

    patient_id = fields.Many2one('res.partner', string='Patient', required=True, domain=[('is_dental_patient', '=', True)], tracking=True)
    patient_phone = fields.Char(related='patient_id.phone', string='Phone', readonly=True)
    patient_email = fields.Char(related='patient_id.email', string='Email', readonly=True)

    appointment_id = fields.Many2one('dental.appointment', string='Original Appointment')
    doctor_id = fields.Many2one('hr.employee', string='Doctor', domain=[('is_dentist', '=', True)], tracking=True)
    treatment_id = fields.Many2one('product.template', string='Treatment', domain=[('is_dental_treatment', '=', True)])
    
    date = fields.Date(string='Follow-up Date', required=True, default=fields.Date.context_today, tracking=True)
    reason = fields.Text(string='Reason')
    priority = fields.Selection([
        ('0', 'Normal'),
        ('1', 'Important'),
        ('2', 'Urgent')
    ], string='Priority', default='0', tracking=True)
    
    state = fields.Selection([
        ('pending', 'Pending'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='pending', tracking=True)
    
    notes = fields.Text(string='Notes')

    def action_done(self):
        for record in self:
            record.state = 'done'
            record.message_post(body=_("Follow-up marked as completed."))
            
    def action_cancel(self):
        for record in self:
            record.state = 'cancelled'

    def action_book_followup_appointment(self):
        """Directly open appointment booking form for this follow-up patient."""
        self.ensure_one()
        start_time = fields.Datetime.now()
        end_time = start_time + timedelta(minutes=30)
        form_view = self.env.ref('dental_appointment.view_dental_appointment_form', raise_if_not_found=False)
        
        # Mark follow up as done when booking
        self.state = 'done'
        self.message_post(body=_("Appointment booking opened for this follow-up."))
        
        return {
            'name': _('Book Follow-up Appointment - %s') % (self.patient_id.name or ''),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.appointment',
            'view_mode': 'form',
            'views': [(form_view.id, 'form')] if form_view else [(False, 'form')],
            'target': 'current',
            'context': {
                'default_patient_id': self.patient_id.id,
                'default_doctor_id': self.doctor_id.id if self.doctor_id else False,
                'default_treatment_id': self.treatment_id.id if self.treatment_id else False,
                'default_date_start': start_time,
                'default_date_end': end_time,
                'default_reason': f"Follow-up: {self.reason or ''}".strip(),
            }
        }
