"""Dental case -> ABDM health records (FHIR documents).

A dental case is one ABDM *care context*. It produces:

* one OPConsultation record per signed-off clinical examination (chief
  complaint, examination summary, allergies, medical history, diagnoses with
  ICD-10 code and tooth, procedures performed at that visit, medicines
  prescribed at that visit, recommended treatment / follow-up);
* one Prescription record per issued prescription.
"""
from odoo import fields, models
from odoo.tools import html2plaintext

from odoo.addons.abdm_base.tools import fhir
from odoo.addons.dental_patient.models.res_partner import clean_allergy_text

ACTIVE_PRESCRIPTION_STATES = ('confirmed', 'issued', 'partially_dispensed', 'fully_dispensed')
GENDER_TO_FHIR = {'male': 'male', 'female': 'female', 'other': 'other'}


def _plain(value):
    return html2plaintext(value or '').strip() if value else ''


class DentalCase(models.Model):
    _name = 'dental.case'
    _inherit = ['dental.case', 'abdm.care.context.mixin']

    # ------------------------------------------------------------------
    # care context hooks (abdm_hip)
    # ------------------------------------------------------------------
    def _abdm_cc_patient(self):
        return self.patient_id

    def _abdm_cc_company(self):
        return self.branch_id or self.env.company

    def _abdm_cc_reference(self):
        return self.name

    def _abdm_cc_display(self):
        day = self.case_date.strftime('%d %b %Y') if self.case_date else ''
        complaint = (self.chief_complaint or '').strip().splitlines()[0][:60] if self.chief_complaint else ''
        return ' - '.join(filter(None, ['Dental visit %s' % day, complaint])) or self.name

    def _abdm_cc_hi_types(self):
        types = sorted({r['hi_type'] for r in self._abdm_health_records()})
        return types or ['OPConsultation']

    # ------------------------------------------------------------------
    # participants
    # ------------------------------------------------------------------
    def _abdm_fhir_patient(self):
        partner = self.patient_id
        return fhir.patient(
            local_id=partner.dental_patient_id or str(partner.id),
            name=partner.name,
            abha_number=partner.abha_number,
            abha_address=partner.abha_address,
            gender=GENDER_TO_FHIR.get(partner.gender),
            birth_date=partner.date_of_birth,
            phone=partner.phone,
        )

    def _abdm_fhir_practitioner(self, employee):
        employee = employee or self.doctor_id
        if not employee:
            return fhir.practitioner(self.env.user.name)
        return fhir.practitioner(employee.name, employee.sudo().registration_number or None)

    def _abdm_fhir_organization(self):
        company = self.branch_id or self.env.company
        return fhir.organization(company.abdm_hip_name or company.name, company.abdm_hip_id or None,
                                 phone=company.phone, email=company.email)

    # ------------------------------------------------------------------
    # records
    # ------------------------------------------------------------------
    def _abdm_op_consultation(self, exam):
        """FHIR document for one signed-off examination."""
        patient = self._abdm_fhir_patient()
        doctor = self._abdm_fhir_practitioner(exam.doctor_id)
        clinic = self._abdm_fhir_organization()
        when = exam.completed_date or exam.examination_date
        visit = fhir.encounter(patient, exam.examination_date or when, when)
        sections, resources = [], []

        complaint = (exam.chief_complaint or self.chief_complaint or '').strip()
        if complaint:
            cond = fhir.condition(patient, complaint, recorded=when, category='Chief complaint')
            sections.append(fhir.section(fhir.SECTION_CHIEF_COMPLAINT, [cond]))
            resources.append(cond)

        partner = self.patient_id
        allergy_text = clean_allergy_text(partner.allergies)
        if partner.allergy_status == 'known' and allergy_text:
            allergies = [fhir.allergy(patient, line.strip(), recorded=partner.allergy_verified_date)
                         for line in allergy_text.replace(';', '\n').replace(',', '\n').splitlines() if line.strip()]
            sections.append(fhir.section(fhir.SECTION_ALLERGIES, allergies))
            resources += allergies
        elif partner.allergy_status == 'none':
            sections.append(fhir.section(fhir.SECTION_ALLERGIES, [], text='No known allergies'))

        history = []
        conditions_text = _plain(partner.existing_conditions)
        if conditions_text:
            history.append(fhir.condition(patient, conditions_text, category='Medical history'))
        diagnoses = exam.diagnosis_ids if 'diagnosis_ids' in exam._fields else self.diagnosis_ids
        for diag in diagnoses:
            name = diag.diagnosis_id.name or diag.diagnosis_name or ''
            if not name:
                continue
            history.append(fhir.condition(
                patient, name, code=diag.diagnosis_id.code or None,
                active=diag.status != 'resolved', recorded=diag.date or when,
                body_site=diag.tooth_reference and 'Tooth %s' % diag.tooth_reference,
                note=diag.notes, category='Diagnosis'))
        if history:
            sections.append(fhir.section(fhir.SECTION_MEDICAL_HISTORY, history))
            resources += history

        if exam.examination_summary:
            obs = fhir.observation(patient, 'Dental examination', exam.examination_summary, when, doctor)
            sections.append(fhir.section(fhir.SECTION_PHYSICAL_EXAM, [obs], text=exam.examination_summary))
            resources.append(obs)

        procedures = []
        sessions = self.treatment_session_ids.filtered(
            lambda s: s.state == 'completed' and exam.appointment_id and s.appointment_id == exam.appointment_id)
        for session in sessions:
            treatment = session.performed_treatment_id or session.planned_treatment_id
            procedures.append(fhir.procedure(
                patient, treatment.name or session.name, performed=session.session_date,
                body_site=(session.performed_tooth_reference or session.tooth_reference)
                and 'Tooth %s' % (session.performed_tooth_reference or session.tooth_reference),
                note=session.procedure_notes, performer=doctor))
        if procedures:
            sections.append(fhir.section(fhir.SECTION_PROCEDURE, procedures))
            resources += procedures

        if 'prescription_ids' in self._fields and exam.appointment_id:
            meds = []
            for rx in self.prescription_ids.filtered(
                    lambda p: p.state in ACTIVE_PRESCRIPTION_STATES and p.appointment_id == exam.appointment_id):
                meds += self._abdm_medication_requests(rx, patient, doctor)
            if meds:
                sections.append(fhir.section(fhir.SECTION_MEDICATIONS, meds))
                resources += meds

        plan = '\n'.join(filter(None, [
            exam.recommended_treatment and 'Recommended treatment: %s' % exam.recommended_treatment.strip(),
            *('Follow-up on %s: %s' % (f.date, (f.reason or '').strip()) for f in self.follow_up_ids
              if f.date and f.state in ('pending', 'booked')),
        ]))
        if plan:
            sections.append(fhir.section(fhir.SECTION_FOLLOW_UP, [], text=plan))

        if not sections:
            return None
        return fhir.document_bundle(
            'OPConsultation', 'Consultation Report', patient, doctor, clinic, sections, resources,
            when=when, encounter_res=visit, local_reference=exam.name)

    def _abdm_medication_requests(self, rx, patient, doctor):
        reasons = []
        if rx.diagnosis:
            reasons.append(fhir.condition(patient, rx.diagnosis, category='Diagnosis'))
        result = list(reasons)
        for line in rx.line_ids:
            medicine = line.medicine_id.display_name or line.generic_name or ''
            if line.strength and line.strength not in medicine:
                medicine = '%s %s' % (medicine, line.strength)
            dosage = ', '.join(filter(None, [
                line.dose, line.frequency_label,
                line.duration and '%s days' % line.duration,
            ]))
            route = dict(line._fields['route']._description_selection(self.env)).get(line.route)
            result.append(fhir.medication_request(
                patient, doctor, medicine.strip(), rx.prescription_date, dosage, route=route,
                instructions=line.instructions, reasons=reasons, quantity=line.quantity,
                duration_days=line.duration))
        return result

    def _abdm_prescription_record(self, rx):
        patient = self._abdm_fhir_patient()
        doctor = self._abdm_fhir_practitioner(rx.dentist_id)
        clinic = self._abdm_fhir_organization()
        resources = self._abdm_medication_requests(rx, patient, doctor)
        meds = [r for r in resources if r['resourceType'] == 'MedicationRequest']
        if not meds:
            return None
        section = fhir.section(fhir.SECTION_PRESCRIPTION, meds, text=rx.clinical_notes or None)
        return fhir.document_bundle(
            'Prescription', 'Prescription', patient, doctor, clinic, [section], resources,
            when=rx.prescription_date, local_reference=rx.name)

    def _abdm_health_records(self, hi_types=None, date_from=None, date_to=None):
        """All shareable records of this case.

        :return: list of dict(hi_type, reference, date, bundle)
        """
        self.ensure_one()
        records = []

        def wanted(hi_type, when):
            if hi_types and hi_type not in hi_types:
                return False
            day = fields.Date.to_date(when) if when else None
            if day and date_from and day < fields.Date.to_date(date_from):
                return False
            if day and date_to and day > fields.Date.to_date(date_to):
                return False
            return True

        for exam in self.examination_ids.filtered(lambda e: e.state == 'done').sorted('examination_date'):
            when = exam.completed_date or exam.examination_date
            if wanted('OPConsultation', when):
                bundle = self._abdm_op_consultation(exam)
                if bundle:
                    records.append({'hi_type': 'OPConsultation', 'reference': exam.name,
                                    'date': fields.Date.to_date(when), 'bundle': bundle})
        if 'prescription_ids' in self._fields:
            for rx in self.prescription_ids.filtered(lambda p: p.state in ACTIVE_PRESCRIPTION_STATES):
                if wanted('Prescription', rx.prescription_date):
                    bundle = self._abdm_prescription_record(rx)
                    if bundle:
                        records.append({'hi_type': 'Prescription', 'reference': rx.name,
                                        'date': rx.prescription_date, 'bundle': bundle})
        return records

    def action_abdm_preview_records(self):
        self.ensure_one()
        return self.env['abdm.fhir.preview'].open(
            '%s - %s' % (self.name, self.patient_id.name), self._abdm_health_records())
