# -*- coding: utf-8 -*-
from odoo import api, models
from odoo.addons.dental_dms.models.dental_dms_service import clean_name
from odoo.addons.dms.tools import file as dms_file_tools


class DentalDmsService(models.AbstractModel):
    _inherit = 'dental.dms.service'

    @api.model
    def _get_folder_permissions(self):
        perms = super()._get_folder_permissions()
        perms['education'] = {
            'dms_group_clinical': 'v',
            'dms_group_frontdesk': 'v',
            'dms_group_management': 'vueds',
        }
        return perms

    @api.model
    def _get_education_folder(self, company, topic):
        """Patient Education Library / <topic> folder of a branch (created on demand)."""
        category = self._get_category_folder(company, 'education')
        if not topic:
            return category
        Directory = self.env['dms.directory'].sudo().with_context(active_test=False)
        folder = Directory.search([('parent_id', '=', category.id), ('dental_edu_topic_id', '=', topic.id)], limit=1)
        if folder:
            return folder
        name = clean_name(topic.name, default=f'Topic {topic.id}')
        names = category.child_directory_ids.mapped('name')
        if name in names:
            name = dms_file_tools.unique_name(name, names)
        return Directory.with_context(check_name=False).create({
            'name': name,
            'parent_id': category.id,
            'company_id': company.id,
            'dental_folder_role': 'subject',
            'dental_doc_type': 'education',
            'dental_edu_topic_id': topic.id,
            'category_id': topic.id,
        })
