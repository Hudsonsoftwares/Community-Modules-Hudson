# -*- coding: utf-8 -*-
from odoo import _, fields, models


class DentalEducationMixin(models.AbstractModel):
    """'Educate Patient' entry point on dental records."""
    _name = 'dental.education.mixin'
    _description = 'Dental Patient Education Entry Point'

    _dental_edu_link_field = False      # field of dental.education.session pointing to this model
    _dental_edu_purpose = 'pre_treatment'

    dental_education_count = fields.Integer(string='Education', compute='_compute_dental_education_count')

    def _dental_edu_domain(self):
        self.ensure_one()
        return [(self._dental_edu_link_field, '=', self.id)]

    def _compute_dental_education_count(self):
        Session = self.env['dental.education.session']
        for rec in self:
            rec.dental_education_count = Session.search_count(rec._dental_edu_domain()) if rec.id else 0

    def _dental_edu_session_vals(self):
        self.ensure_one()
        vals = {self._dental_edu_link_field: self.id, 'purpose': self._dental_edu_purpose}
        for fname, target in (('patient_id', 'patient_id'), ('case_id', 'case_id'),
                              ('appointment_id', 'appointment_id')):
            if fname in self._fields and self[fname] and target != self._dental_edu_link_field:
                vals[target] = self[fname].id
        if 'company_id' in self._fields and self.company_id:
            vals['company_id'] = self.company_id.id
        return vals

    def action_dental_educate_patient(self):
        """Create an education session pre-filled with recommended media and open it."""
        self.ensure_one()
        session = self.env['dental.education.session'].create(self._dental_edu_session_vals())
        session.action_load_recommendations()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Patient Education'),
            'res_model': 'dental.education.session',
            'res_id': session.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_dental_education_sessions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Patient Education - %s', self.display_name),
            'res_model': 'dental.education.session',
            'view_mode': 'list,form',
            'domain': self._dental_edu_domain(),
            'context': dict(self._dental_edu_session_vals(), create=False),
        }


class ResPartner(models.Model):
    _name = 'res.partner'
    _inherit = ['res.partner', 'dental.education.mixin']
    _dental_edu_link_field = 'patient_id'
    _dental_edu_purpose = 'general'

    def _dental_edu_session_vals(self):
        return {'patient_id': self.id, 'purpose': self._dental_edu_purpose}


class DentalClinicalExamination(models.Model):
    _name = 'dental.clinical.examination'
    _inherit = ['dental.clinical.examination', 'dental.education.mixin']
    _dental_edu_link_field = 'examination_id'


class DentalCase(models.Model):
    _name = 'dental.case'
    _inherit = ['dental.case', 'dental.education.mixin']
    _dental_edu_link_field = 'case_id'


class DentalTreatmentPlan(models.Model):
    _name = 'dental.treatment.plan'
    _inherit = ['dental.treatment.plan', 'dental.education.mixin']
    _dental_edu_link_field = 'treatment_plan_id'


class DentalTreatmentSession(models.Model):
    _name = 'dental.treatment.session'
    _inherit = ['dental.treatment.session', 'dental.education.mixin']
    _dental_edu_link_field = 'treatment_session_id'
    _dental_edu_purpose = 'post_care'

    def _dental_edu_session_vals(self):
        vals = super()._dental_edu_session_vals()
        if self.plan_id:
            vals['treatment_plan_id'] = self.plan_id.id
        return vals
