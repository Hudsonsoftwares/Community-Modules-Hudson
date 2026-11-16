# -*- coding: utf-8 -*-
from odoo import fields, models


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    dental_channel_type = fields.Selection(
        selection_add=[('teleconsult', 'Online Patient Consultation')],
        ondelete={'teleconsult': 'set null'})


class DiscussChannelMember(models.Model):
    _inherit = 'discuss.channel.member'

    def _get_recording_permissions(self, user, sfu_url=True):
        """Online consultations may only be recorded when the branch allows it and the patient consented."""
        permissions = super()._get_recording_permissions(user, sfu_url)
        channel = self.channel_id[:1].sudo()
        if channel.dental_channel_type == 'teleconsult':
            appointment = channel.dental_appointment_id
            allowed = bool(
                appointment
                and appointment._teleconsult_company().dental_teleconsult_allow_recording
                and appointment.teleconsult_recording_consent
                and user and user.has_group('dental_base.group_dental_dentist')
            )
            if not allowed:
                permissions = {key: False for key in permissions}
        return permissions
