# -*- coding: utf-8 -*-
from odoo import api, models


class DentalDmsService(models.AbstractModel):
    _inherit = 'dental.dms.service'

    @api.model
    def _get_folder_permissions(self):
        perms = super()._get_folder_permissions()
        perms.setdefault('lab', {})['dental_dms_lab.dms_group_laboratory'] = 'vue'
        return perms


# Lab documents are linked to the patient and to the lab order / dispatch / receipt only, not to the
# case: laboratory staff cannot read dental cases, so a case link would hide the documents from them
# (dental_dms case-privacy rule). Visibility is governed by the Laboratory folder permissions
# (clinical team + laboratory) and branch isolation.
UNLINKED = {'dental_case_id': False, 'dental_appointment_id': False, 'dental_examination_id': False,
            'dental_treatment_plan_id': False}


class DentalLabOrder(models.Model):
    _name = 'dental.lab.order'
    _inherit = ['dental.lab.order', 'dental.dms.document.mixin']
    _dental_dms_default_type = 'lab'

    def _dental_dms_folder_type(self, attachment):
        return 'lab'

    def _dental_dms_links(self):
        return dict(super()._dental_dms_links(), **UNLINKED)

    def _dental_dms_document_domain(self):
        self.ensure_one()
        receipts = self.env['dental.lab.receipt'].search([('order_id', '=', self.id)])
        dispatches = self.env['dental.lab.dispatch'].search([('order_id', '=', self.id)])
        return ['|', '|',
                '&', ('dental_source_model', '=', self._name), ('dental_source_id', '=', self.id),
                '&', ('dental_source_model', '=', 'dental.lab.receipt'), ('dental_source_id', 'in', receipts.ids),
                '&', ('dental_source_model', '=', 'dental.lab.dispatch'), ('dental_source_id', 'in', dispatches.ids)]


class _LabOrderChildMixin(models.AbstractModel):
    _name = 'dental.dms.lab.child.mixin'
    _inherit = 'dental.dms.document.mixin'
    _description = 'Dental Lab Child Documents'

    def _dental_dms_folder_type(self, attachment):
        return 'lab'

    def _dental_dms_links(self):
        vals = dict(super()._dental_dms_links(), **UNLINKED)
        vals['dental_patient_id'] = vals.get('dental_patient_id') or self.order_id.patient_id.id
        return vals


class DentalCase(models.Model):
    _inherit = 'dental.case'

    def _dental_dms_document_domain(self):
        domain = super()._dental_dms_document_domain()
        orders = self.env['dental.lab.order'].search([('case_id', '=', self.id)])
        return ['|'] + domain + ['&', ('dental_source_model', 'in', ('dental.lab.order', 'dental.lab.dispatch',
                                                                    'dental.lab.receipt')),
                                 ('dental_source_id', 'in', orders.ids + self.env['dental.lab.dispatch'].search(
                                     [('order_id', 'in', orders.ids)]).ids + self.env['dental.lab.receipt'].search(
                                     [('order_id', 'in', orders.ids)]).ids)]


class DentalLabDispatch(models.Model):
    _name = 'dental.lab.dispatch'
    _inherit = ['dental.lab.dispatch', 'dental.dms.lab.child.mixin']


class DentalLabReceipt(models.Model):
    _name = 'dental.lab.receipt'
    _inherit = ['dental.lab.receipt', 'dental.dms.lab.child.mixin']
