# -*- coding: utf-8 -*-
from odoo import models


class MailTemplate(models.Model):
    _inherit = 'mail.template'

    def send_mail(self, res_id, *args, **kwargs):
        """Online visits must not receive the in-clinic confirmation ("please arrive 10 minutes early").

        * ``dental_teleconsult_invite`` (dental.appointment.action_confirm): send the video invitation instead.
        * ``dental_teleconsult_booking`` (create_appointment_booking): a pending online request gets the
          "request received" email; an already-confirmed one got its invitation when it was created.
        """
        ctx = self.env.context
        if (ctx.get('dental_teleconsult_invite') or ctx.get('dental_teleconsult_booking')) \
                and len(self) == 1 and self.model == 'dental.appointment':
            confirmation = self.env.ref('dental_appointment.email_template_appointment_confirmation',
                                        raise_if_not_found=False)
            appointment = self.env['dental.appointment'].browse(res_id)
            if confirmation and self == confirmation and appointment.consultation_mode == 'online':
                clean = self.with_context(dental_teleconsult_invite=False, dental_teleconsult_booking=False)
                if ctx.get('dental_teleconsult_invite'):
                    xmlid = 'dental_teleconsult.mail_template_teleconsult_invitation'
                elif appointment.state == 'pending':
                    xmlid = 'dental_teleconsult.mail_template_teleconsult_request_received'
                else:
                    return False
                replacement = clean.env.ref(xmlid, raise_if_not_found=False)
                if replacement:
                    return replacement.send_mail(res_id, *args, **kwargs)
        return super().send_mail(res_id, *args, **kwargs)
