# -*- coding: utf-8 -*-
from odoo import api, models


class DentalDmsService(models.AbstractModel):
    _inherit = 'dental.dms.service'

    @api.model
    def _get_folder_permissions(self):
        perms = super()._get_folder_permissions()
        perms.setdefault('prescription', {})['dental_dms_pharmacy.dms_group_pharmacy'] = 'vu'
        return perms


# Pharmacy documents are linked to the patient and to the prescription / dispensing record only, not
# to the case: the pharmacy team cannot read dental cases, so a case link would hide the documents
# from them (dental_dms case-privacy rule). Visibility is governed by the Prescriptions folder
# permissions (clinical team + pharmacy) and branch isolation.
UNLINKED = {'dental_case_id': False, 'dental_appointment_id': False, 'dental_examination_id': False,
            'dental_treatment_plan_id': False}


class DentalPrescription(models.Model):
    _name = 'dental.prescription'
    _inherit = ['dental.prescription', 'dental.dms.document.mixin']

    def _dental_dms_folder_type(self, attachment):
        return 'prescription'

    def _dental_dms_links(self):
        return dict(super()._dental_dms_links(), **UNLINKED)


class DentalPharmacyDispense(models.Model):
    _name = 'dental.pharmacy.dispense'
    _inherit = ['dental.pharmacy.dispense', 'dental.dms.document.mixin']

    def _dental_dms_folder_type(self, attachment):
        return 'prescription'

    def _dental_dms_links(self):
        vals = dict(super()._dental_dms_links(), **UNLINKED)
        vals['dental_patient_id'] = vals.get('dental_patient_id') or self.prescription_id.patient_id.id
        return vals


class DentalCase(models.Model):
    _inherit = 'dental.case'

    def _dental_dms_document_domain(self):
        domain = super()._dental_dms_document_domain()
        prescriptions = self.env['dental.prescription'].search([('case_id', '=', self.id)])
        dispenses = self.env['dental.pharmacy.dispense'].search([('case_id', '=', self.id)])
        return ['|', '|'] + domain + [
            '&', ('dental_source_model', '=', 'dental.prescription'), ('dental_source_id', 'in', prescriptions.ids),
            '&', ('dental_source_model', '=', 'dental.pharmacy.dispense'), ('dental_source_id', 'in', dispenses.ids)]
