import re
from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

# (keywords, days until review, reason label, fallback treatment name)
FOLLOWUP_RULES = [
    (('surgery', 'extraction', 'implant', 'wisdom'), 3, "Post-Surgical Suture & Healing Check", "Surgery / Extraction"),
    (('root canal', 'endodontic', 'rct'), 7, "RCT Follow-up & Permanent Restoration", "Root Canal"),
    (('braces', 'ortho', 'aligner'), 28, "Orthodontic Adjustment Checkup", "Braces"),
    (('filling', 'crown', 'bridge', 'restoration'), 7, "Post-Restoration Occlusion & Sensitivity Check", "Filling / Crown"),
    (('scaling', 'cleaning', 'prophylaxis'), 14, "Gingival Health & Post-Scaling Review", "Scaling"),
]

INTERVAL_UNIT_DAYS = {'day': 1, 'week': 7, 'month': 30, 'year': 365}


class DentalFollowUp(models.Model):
    _name = 'dental.follow.up'
    _description = 'Dental Follow-up'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'dental.company.mixin']
    _order = 'date asc, id desc'

    patient_id = fields.Many2one('res.partner', string='Patient', required=True, domain=[('is_dental_patient', '=', True)], tracking=True)
    patient_phone = fields.Char(related='patient_id.phone', string='Phone', readonly=True)
    patient_email = fields.Char(related='patient_id.email', string='Email', readonly=True)

    appointment_id = fields.Many2one('dental.appointment', string='Original Appointment', check_company=True)

    @api.depends('appointment_id.company_id')
    def _compute_company_id(self):
        self._set_company_from('appointment_id')
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
        ('booked', 'Booked'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='pending', tracking=True)
    booked_appointment_id = fields.Many2one('dental.appointment', string='Booked Appointment', readonly=True, copy=False,
                                            index='btree_not_null',
                                            help='Appointment booked for this follow-up. Set only once the appointment exists.')
    
    notes = fields.Text(string='Notes')

    @api.model
    def _suggest_followup(self, treatment, fallback=''):
        """Return (days, reason) for a post-treatment review based on clinical keyword rules."""
        name = treatment.name if treatment else ''
        text = (name or fallback or '').lower()
        for keywords, days, label, default_name in FOLLOWUP_RULES:
            if any(w in text for w in keywords):
                return days, f"{label}: {name or default_name}"
        return 7, f"Post-Treatment Review: {name or fallback or 'Consultation'}"

    @api.model
    def _parse_interval_days(self, interval):
        """Convert free-text intervals such as '10 days', '2 Weeks' or '6 Months' into days."""
        match = re.search(r'(\d+)\s*(day|week|month|year)', (interval or '').lower())
        if not match:
            return 0
        return int(match.group(1)) * INTERVAL_UNIT_DAYS[match.group(2)]

    def action_done(self):
        for record in self:
            record.state = 'done'
            record.message_post(body=_("Follow-up marked as completed."))

    def action_cancel(self):
        for record in self:
            record.state = 'cancelled'

    def action_reset_to_pending(self):
        """Re-open a cancelled follow-up, or one whose booking is no longer active."""
        for record in self:
            if record.state == 'booked' and record.booked_appointment_id.state not in ('cancelled', 'no_show'):
                raise UserError(_("This follow-up is booked as %s; cancel that appointment first.",
                                  record.booked_appointment_id.name))
        self.write({'state': 'pending', 'booked_appointment_id': False})

    def _link_booked_appointment(self, appointment):
        """Called once the appointment really exists: the follow-up is booked, not done."""
        self.ensure_one()
        if self.state != 'pending':
            return False
        if appointment.patient_id != self.patient_id:
            raise UserError(_("The appointment is for %(appt)s but the follow-up is for %(fu)s.",
                              appt=appointment.patient_id.display_name, fu=self.patient_id.display_name))
        self.write({'state': 'booked', 'booked_appointment_id': appointment.id})
        self.message_post(body=_("Follow-up booked: appointment %s.", appointment.name))
        return True

    def _sync_from_booked_appointment(self):
        """Attended visit completes the follow-up; a cancelled or missed one puts it back to pending."""
        for record in self.filtered(lambda f: f.state == 'booked'):
            appt = record.booked_appointment_id
            if appt.state == 'completed':
                record.state = 'done'
                record.message_post(body=_("Follow-up completed: visit %s attended.", appt.name))
            elif appt.state in ('cancelled', 'no_show'):
                record.write({'state': 'pending', 'booked_appointment_id': False})
                record.message_post(body=_("Booked appointment %(appt)s was %(state)s; the follow-up is pending again.",
                                           appt=appt.name, state=dict(appt._fields['state'].selection)[appt.state]))

    def action_book_followup_appointment(self):
        """Directly open appointment booking form for this follow-up patient."""
        self.ensure_one()
        start_time = fields.Datetime.now()
        end_time = start_time + timedelta(minutes=30)
        form_view = self.env.ref('dental_appointment.view_dental_appointment_form', raise_if_not_found=False)
        
        if self.state != 'pending':
            raise UserError(_("Only pending follow-ups can be booked (this one is %s).",
                              dict(self._fields['state'].selection)[self.state]))
        # The follow-up is marked booked by dental.appointment.create, i.e. only once the
        # appointment has actually been saved; closing the form without saving changes nothing.
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
                'dental_follow_up_id': self.id,
            }
        }
