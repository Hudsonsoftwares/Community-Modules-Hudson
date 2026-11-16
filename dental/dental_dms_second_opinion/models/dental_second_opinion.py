# -*- coding: utf-8 -*-
from odoo import api, models


class DentalDmsService(models.AbstractModel):
    _inherit = 'dental.dms.service'

    @api.model
    def _get_folder_permissions(self):
        perms = super()._get_folder_permissions()
        perms.setdefault('second_opinion', {})['dental_dms_second_opinion.dms_group_specialist'] = 'vu'
        return perms


class DentalSecondOpinion(models.Model):
    """Specialists can read the cases they review (dental_second_opinion rule), so the case link and the
    dental_dms case-privacy rule give them exactly the documents of their own requests."""
    _name = 'dental.second.opinion'
    _inherit = ['dental.second.opinion', 'dental.dms.document.mixin']

    def _dental_dms_folder_type(self, attachment):
        guessed = self._dental_dms_guess_type(attachment, 'second_opinion')
        return 'imaging' if guessed == 'imaging' else 'second_opinion'
