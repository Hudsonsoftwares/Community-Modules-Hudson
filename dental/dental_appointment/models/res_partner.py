from datetime import timedelta
from odoo import models, fields, api, _

class ResPartner(models.Model):
    _inherit = 'res.partner'

    appointment_ids = fields.One2many('dental.appointment', 'patient_id', string='Appointments')
    appointment_count = fields.Integer(string='Appointment Count', compute='_compute_appointment_count')
    
    def _compute_appointment_count(self):
        for record in self:
            record.appointment_count = len(record.appointment_ids)

    def action_book_appointment(self):
        """Immediately open appointment form in create mode with patient pre-filled."""
        self.ensure_one()
        start_time = fields.Datetime.now()
        end_time = start_time + timedelta(minutes=30)
        
        form_view = self.env.ref('dental_appointment.view_dental_appointment_form', raise_if_not_found=False)
        branch_id = getattr(self, 'active_clinic_id', False) and self.active_clinic_id.id or self.env.company.id

        return {
            'name': _('Book Appointment - %s') % (self.name or ''),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.appointment',
            'view_mode': 'form',
            'views': [(form_view.id, 'form')] if form_view else [(False, 'form')],
            'target': 'current',
            'context': {
                'default_patient_id': self.id,
                'default_date_start': start_time,
                'default_date_end': end_time,
                'default_branch_id': branch_id,
            }
        }

    def action_open_guided_booking_flow(self):
        """Open the interactive 5-step guided booking flow for this patient."""
        self.ensure_one()
        return {
            'name': _('Guided Booking Flow - %s') % (self.name or ''),
            'type': 'ir.actions.client',
            'tag': 'dental_appointment.book_appointment_flow',
            'target': 'current',
            'context': {
                'default_patient_id': self.id,
            }
        }

    def action_view_appointments(self):
        self.ensure_one()
        if not self.appointment_ids:
            return self.action_book_appointment()

        tree_view = self.env.ref('dental_appointment.view_dental_appointment_tree', raise_if_not_found=False)
        form_view = self.env.ref('dental_appointment.view_dental_appointment_form', raise_if_not_found=False)
        
        action = {
            'name': _('Appointments - %s') % (self.name or ''),
            'type': 'ir.actions.act_window',
            'view_mode': 'list,form,calendar',
            'views': [
                (tree_view.id if tree_view else False, 'list'),
                (form_view.id if form_view else False, 'form'),
            ],
            'res_model': 'dental.appointment',
            'domain': [('patient_id', '=', self.id)],
            'context': {'default_patient_id': self.id},
        }
        if len(self.appointment_ids) == 1:
            action['views'] = [(form_view.id if form_view else False, 'form')]
            action['res_id'] = self.appointment_ids.id
        return action
