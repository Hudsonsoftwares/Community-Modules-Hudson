# -*- coding: utf-8 -*-
"""Dental document sources: every model below files its attachments into the DMS."""
import html
import json

from odoo import _, fields, models

PATIENT_DOCUMENT_TYPES = {
    'xray': 'imaging',
    'prescription': 'prescription',
    'lab_report': 'lab',
    'referral': 'clinical',
    'insurance': 'patient',
    'other': 'patient',
}


class ResPartner(models.Model):
    _name = 'res.partner'
    _inherit = ['res.partner', 'dental.dms.document.mixin']

    def _dental_dms_folder_type(self, attachment):
        self.ensure_one()
        if not self.is_dental_patient:
            return False   # only patients; other contacts keep the standard DMS behaviour
        return self._dental_dms_guess_type(attachment, 'patient')

    def _dental_dms_links(self):
        self.ensure_one()
        return {'dental_patient_id': self.id if self.is_dental_patient else False}

    def _dental_dms_document_domain(self):
        self.ensure_one()
        return [('dental_patient_id', '=', self.id)]


class DentalAppointment(models.Model):
    _name = 'dental.appointment'
    _inherit = ['dental.appointment', 'dental.dms.document.mixin']

    def _dental_dms_links(self):
        vals = super()._dental_dms_links()
        vals['dental_appointment_id'] = self.id
        return vals

    def _dental_dms_document_domain(self):
        self.ensure_one()
        return [('dental_appointment_id', '=', self.id)]


class DentalCase(models.Model):
    _name = 'dental.case'
    _inherit = ['dental.case', 'dental.dms.document.mixin']
    _dental_dms_default_type = 'clinical'

    def _dental_dms_links(self):
        vals = super()._dental_dms_links()
        vals['dental_case_id'] = self.id
        return vals

    def _dental_dms_document_domain(self):
        self.ensure_one()
        return [('dental_case_id', '=', self.id)]

    def action_dental_snapshot_odontogram(self):
        """Store the current odontogram (chart + tooth findings) as a dated document of the case."""
        self.ensure_one()
        self.check_access('write')
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        name = f'Odontogram {self.name} {now.strftime("%Y-%m-%d %H%M")}.html'
        raw = self._dental_odontogram_html(now).encode('utf-8')
        self.env['dental.dms.service']._store_document(
            self, name, raw, doc_type='odontogram', mimetype='text/html',
            extra={'dental_document_date': now.date()})
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'success', 'title': _('Odontogram saved'),
                       'message': _('A snapshot of the odontogram was filed in the patient documents.'),
                       'next': {'type': 'ir.actions.act_window_close'}},
        }

    def _dental_odontogram_html(self, now):
        esc = html.escape
        try:
            chart = json.loads(self.odontogram_chart or '{}')
        except ValueError:
            chart = {}
        rows = ''.join(
            f'<tr><td>{esc(f.tooth_number or "")}</td><td>{esc(f.tooth_name or "")}</td>'
            f'<td>{esc(f.display_name or "")}</td>'
            f'<td>{esc(dict(f._fields["state"]._description_selection(self.env)).get(f.state, "") or "")}</td></tr>'
            for f in self.tooth_finding_ids)
        chart_rows = ''.join(
            f'<tr><td>{esc(str(tooth))}</td><td><code>{esc(json.dumps(data, ensure_ascii=False))}</code></td></tr>'
            for tooth, data in sorted(chart.items(), key=lambda kv: str(kv[0])))
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{esc(self.name)} - Odontogram</title>
<style>body{{font-family:Arial,sans-serif;margin:24px;color:#222}}table{{border-collapse:collapse;width:100%;margin:12px 0}}
td,th{{border:1px solid #ccc;padding:6px;text-align:left;font-size:13px}}th{{background:#f2f4f7}}</style></head><body>
<h2>Odontogram snapshot - {esc(self.name)}</h2>
<p><b>Patient:</b> {esc(self.patient_id.display_name or '')}<br/>
<b>Doctor:</b> {esc(self.doctor_id.name or '')}<br/><b>Branch:</b> {esc(self.company_id.name or '')}<br/>
<b>Captured:</b> {esc(now.strftime('%Y-%m-%d %H:%M'))} by {esc(self.env.user.name)}</p>
<h3>Tooth findings</h3><table><tr><th>Tooth</th><th>Anatomy</th><th>Finding</th><th>Status</th></tr>{rows or '<tr><td colspan="4">-</td></tr>'}</table>
<h3>Chart data</h3><table><tr><th>Tooth</th><th>Recorded state</th></tr>{chart_rows or '<tr><td colspan="2">-</td></tr>'}</table>
</body></html>"""


class DentalClinicalExamination(models.Model):
    _name = 'dental.clinical.examination'
    _inherit = ['dental.clinical.examination', 'dental.dms.document.mixin']
    _dental_dms_default_type = 'clinical'

    def _dental_dms_links(self):
        vals = super()._dental_dms_links()
        vals['dental_examination_id'] = self.id
        return vals

    def _dental_dms_document_domain(self):
        self.ensure_one()
        return [('dental_examination_id', '=', self.id)]


class DentalPatientDiagnosis(models.Model):
    _name = 'dental.patient.diagnosis'
    _inherit = ['dental.patient.diagnosis', 'dental.dms.document.mixin']
    _dental_dms_default_type = 'clinical'


class DentalToothFinding(models.Model):
    _name = 'dental.tooth.finding'
    _inherit = ['dental.tooth.finding', 'dental.dms.document.mixin']
    _dental_dms_default_type = 'odontogram'

    def _dental_dms_folder_type(self, attachment):
        self.ensure_one()
        guessed = self._dental_dms_guess_type(attachment, 'clinical')
        return 'imaging' if guessed == 'imaging' else 'odontogram'


class DentalTreatmentPlan(models.Model):
    _name = 'dental.treatment.plan'
    _inherit = ['dental.treatment.plan', 'dental.dms.document.mixin']
    _dental_dms_default_type = 'treatment'

    dental_consent_required = fields.Boolean(string='Consent Required', compute='_compute_dental_consent')
    dental_consent_count = fields.Integer(string='Consent Forms', compute='_compute_dental_consent')

    def _compute_dental_consent(self):
        DmsFile = self.env['dms.file']
        for plan in self:
            plan.dental_consent_required = any(plan.line_ids.mapped('treatment_id.is_consent_required'))
            plan.dental_consent_count = DmsFile.search_count([
                ('dental_treatment_plan_id', '=', plan.id), ('dental_doc_type', '=', 'consent')]) if plan.id else 0

    def _dental_dms_links(self):
        vals = super()._dental_dms_links()
        vals['dental_treatment_plan_id'] = self.id
        return vals

    def _dental_dms_document_domain(self):
        self.ensure_one()
        return [('dental_treatment_plan_id', '=', self.id)]

    def action_dental_documents(self):
        action = super().action_dental_documents()
        if self.env.context.get('dental_dms_consent_only'):
            action['domain'] = action['domain'] + [('dental_doc_type', '=', 'consent')]
            action['name'] = _('Consent Forms - %s', self.display_name)
        return action

    def action_dental_add_consent(self):
        action = self.action_dental_add_document()
        action['name'] = _('Add Signed Consent')
        action['context'] = dict(action['context'], default_doc_type='consent')
        return action


class DentalTreatmentSession(models.Model):
    _name = 'dental.treatment.session'
    _inherit = ['dental.treatment.session', 'dental.dms.document.mixin']
    _dental_dms_default_type = 'treatment'


class DentalPatientDocument(models.Model):
    """Existing "Previous Records & X-Rays" records: their file is filed, by document type."""
    _name = 'dental.patient.document'
    _inherit = ['dental.patient.document', 'dental.dms.document.mixin']

    def _dental_dms_routable_fields(self):
        return {'file'}

    def _dental_dms_folder_type(self, attachment):
        self.ensure_one()
        return PATIENT_DOCUMENT_TYPES.get(self.document_type, 'patient')

    def _dental_dms_links(self):
        vals = super()._dental_dms_links()
        vals['dental_document_date'] = self.document_date
        return vals


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'dental.dms.document.mixin']

    def _dental_dms_folder_type(self, attachment):
        self.ensure_one()
        # Only patient billing; vendor bills etc. stay with the existing Accounting folder rules.
        if self.is_invoice(include_receipts=True) and self.move_type.startswith('out_') \
                and self.partner_id.commercial_partner_id.is_dental_patient:
            return 'billing'
        return False

    def _dental_dms_links(self):
        self.ensure_one()
        patient = self.partner_id if self.partner_id.is_dental_patient else self.partner_id.commercial_partner_id
        return {
            'dental_patient_id': patient.id if patient.is_dental_patient else False,
            'dental_case_id': self.dental_case_id.id,
        }


class HrEmployee(models.Model):
    _name = 'hr.employee'
    _inherit = ['hr.employee', 'dental.dms.document.mixin']

    def _dental_dms_folder_type(self, attachment):
        return 'staff'

    def _dental_dms_links(self):
        self.ensure_one()
        return {'dental_employee_id': self.id}

    def _dental_dms_document_domain(self):
        self.ensure_one()
        return ['|', ('dental_employee_id', '=', self.id),
                '&', ('dental_source_model', '=', self._name), ('dental_source_id', '=', self.id)]


class PurchaseOrder(models.Model):
    _name = 'purchase.order'
    _inherit = ['purchase.order', 'dental.dms.document.mixin']

    def _dental_dms_folder_type(self, attachment):
        return 'purchase'

    def _dental_dms_links(self):
        return {}


class CrmLead(models.Model):
    _name = 'crm.lead'
    _inherit = ['crm.lead', 'dental.dms.document.mixin']

    def _dental_dms_folder_type(self, attachment):
        self.ensure_one()
        if self.patient_id:
            return self._dental_dms_guess_type(attachment, 'patient')
        return False

    def _dental_dms_links(self):
        self.ensure_one()
        return {'dental_patient_id': self.patient_id.id if self.patient_id else False}

    def _dental_dms_document_domain(self):
        self.ensure_one()
        if self.patient_id:
            return ['|', ('dental_patient_id', '=', self.patient_id.id),
                    '&', ('dental_source_model', '=', self._name), ('dental_source_id', '=', self.id)]
        return [('dental_source_model', '=', self._name), ('dental_source_id', '=', self.id)]

