# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from odoo import models, fields, api, _

class HrLeave(models.Model):
    _inherit = 'hr.leave'

    conflicting_appointment_ids = fields.Many2many(
        'dental.appointment',
        string='Conflicting Appointments',
        compute='_compute_conflicting_appointments',
        help='Dental appointments scheduled with this doctor during the leave period'
    )
    conflicting_appointment_count = fields.Integer(
        string='Appointment Conflicts',
        compute='_compute_conflicting_appointments',
        help='Count of appointments affected by this leave request'
    )

    @api.depends('employee_id', 'date_from', 'date_to', 'request_date_from', 'request_date_to', 'state')
    def _compute_conflicting_appointments(self):
        appt_obj = self.env['dental.appointment'].sudo()
        for leave in self:
            if leave.employee_id and leave.state not in ('refuse', 'cancel'):
                d_from = leave.date_from or (fields.Datetime.to_datetime(leave.request_date_from) if leave.request_date_from else False)
                d_to = leave.date_to or (fields.Datetime.to_datetime(leave.request_date_to) + timedelta(days=1) if leave.request_date_to else False)
                if d_from and d_to:
                    appts = appt_obj.search([
                        ('doctor_id', '=', leave.employee_id.id),
                        ('state', 'in', ('pending', 'confirmed', 'checked_in', 'in_consultation')),
                        ('date_start', '<', d_to),
                        ('date_end', '>', d_from)
                    ])
                    leave.conflicting_appointment_ids = appts
                    leave.conflicting_appointment_count = len(appts)
                    continue
            leave.conflicting_appointment_ids = [(5, 0, 0)]
            leave.conflicting_appointment_count = 0

    def action_view_conflicting_appointments(self):
        self.ensure_one()
        return {
            'name': _('Conflicting Appointments for Dr. %s') % (self.employee_id.name or ''),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.appointment',
            'view_mode': 'list,form,calendar',
            'domain': [('id', 'in', self.conflicting_appointment_ids.ids)],
            'context': {'default_doctor_id': self.employee_id.id},
        }

    def action_validate(self):
        res = super(HrLeave, self).action_validate()
        self._sync_appointment_leave_conflicts(is_approved=True)
        return res

    def action_approve(self):
        res = super(HrLeave, self).action_approve()
        validated_leaves = self.filtered(lambda l: l.state == 'validate')
        if validated_leaves:
            validated_leaves._sync_appointment_leave_conflicts(is_approved=True)
        return res

    def action_refuse(self):
        res = super(HrLeave, self).action_refuse()
        self._sync_appointment_leave_conflicts(is_approved=False)
        return res

    def action_cancel(self):
        res = super(HrLeave, self).action_cancel()
        self._sync_appointment_leave_conflicts(is_approved=False)
        return res

    def unlink(self):
        self._sync_appointment_leave_conflicts(is_approved=False)
        return super(HrLeave, self).unlink()

    def _sync_appointment_leave_conflicts(self, is_approved=True):
        appt_obj = self.env['dental.appointment'].sudo()
        todo_activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)

        for leave in self:
            if not leave.employee_id:
                continue
            d_from = leave.date_from or (fields.Datetime.to_datetime(leave.request_date_from) if leave.request_date_from else False)
            d_to = leave.date_to or (fields.Datetime.to_datetime(leave.request_date_to) + timedelta(days=1) if leave.request_date_to else False)
            if not d_from or not d_to:
                continue

            if is_approved:
                # Find all pending, confirmed, or checked-in appointments during this leave period
                conflicts = appt_obj.search([
                    ('doctor_id', '=', leave.employee_id.id),
                    ('state', 'in', ('pending', 'confirmed', 'checked_in', 'in_consultation')),
                    ('date_start', '<', d_to),
                    ('date_end', '>', d_from)
                ])
                for appt in conflicts:
                    appt.write({
                        'has_leave_conflict': True,
                        'conflicting_leave_id': leave.id,
                    })
                    msg = _(
                        "⚠️ <b>Doctor Availability Alert:</b> Dr. %s has been approved for leave from %s to %s. "
                        "This appointment conflicts with the approved leave and requires rescheduling."
                    ) % (
                        leave.employee_id.name,
                        fields.Datetime.to_string(leave.date_from),
                        fields.Datetime.to_string(leave.date_to)
                    )
                    appt.message_post(body=msg)
                    if todo_activity_type and not appt.activity_ids.filtered(lambda a: a.activity_type_id == todo_activity_type):
                        appt.activity_schedule(
                            activity_type_id=todo_activity_type.id,
                            summary=_("Reschedule: Doctor on Leave"),
                            note=_("Dr. %s has approved leave (%s to %s). Please contact patient to reschedule.") % (
                                leave.employee_id.name,
                                fields.Datetime.to_string(leave.date_from),
                                fields.Datetime.to_string(leave.date_to)
                            ),
                            user_id=appt.create_uid.id or self.env.uid
                        )
            else:
                # Leave refused, cancelled, or unlinked: clear conflict if no other approved leaves exist
                affected_appts = appt_obj.search([('conflicting_leave_id', '=', leave.id)])
                for appt in affected_appts:
                    other_leave = self.env['hr.leave'].sudo().search([
                        ('id', '!=', leave.id),
                        ('employee_id', '=', appt.doctor_id.id),
                        ('state', '=', 'validate'),
                        ('date_from', '<', appt.date_end),
                        ('date_to', '>', appt.date_start),
                    ], limit=1)
                    if other_leave:
                        appt.write({'conflicting_leave_id': other_leave.id})
                    else:
                        appt.write({
                            'has_leave_conflict': False,
                            'conflicting_leave_id': False,
                        })
                        appt.message_post(body=_(
                            "Doctor leave was refused or cancelled. Availability conflict has been resolved."
                        ))
