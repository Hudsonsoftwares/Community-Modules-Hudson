# -*- encoding: utf-8 -*-
from odoo import api, fields, models, _


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # Override the base module's manual flag to be computed from the
    # actual templates. Same field name and storage so callers and views
    # don't need to change; behaviour now tracks template existence. Still
    # restricted to HR users, as in the base module.
    eh_face_enrolled = fields.Boolean(
        string='Face enrolled',
        compute='_compute_eh_face_enrolled',
        store=True,
        groups='hr.group_hr_user',
        help="True when at least one active face template exists for this employee. Computed from eh_face_template_ids.",
    )

    eh_face_template_ids = fields.One2many(
        'eh.hr.face.template',
        'employee_id',
        string='Face templates',
    )
    eh_face_template_count = fields.Integer(
        string='Active templates',
        compute='_compute_eh_face_template_count',
    )

    @api.depends('eh_face_template_ids', 'eh_face_template_ids.active')
    def _compute_eh_face_template_count(self):
        for employee in self:
            employee.eh_face_template_count = sum(
                1 for t in employee.eh_face_template_ids if t.active
            )

    @api.depends('eh_face_template_ids.active')
    def _compute_eh_face_enrolled(self):
        for employee in self:
            employee.eh_face_enrolled = any(t.active for t in employee.eh_face_template_ids)

    def action_eh_open_face_enrolment(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Enrol face for %s') % self.name,
            'res_model': 'eh.hr.face.enrolment',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_employee_id': self.id},
        }

    def action_eh_view_face_templates(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Face templates for %s') % self.name,
            'res_model': 'eh.hr.face.template',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }
