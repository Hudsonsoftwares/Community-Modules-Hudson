# -*- coding: utf-8 -*-
from odoo import fields, models


class DentalTeleconsultInvite(models.TransientModel):
    _name = 'dental.teleconsult.invite'
    _description = 'Invite a Colleague to an Online Consultation'

    appointment_id = fields.Many2one('dental.appointment', required=True, readonly=True, ondelete='cascade')
    user_ids = fields.Many2many(
        'res.users', string='Colleagues', required=True,
        domain="[('share', '=', False), ('id', '!=', uid)]",
        help="Specialist, assistant or interpreter who joins the video call. They are removed from the "
             "room when the consultation ends.")
    note = fields.Char(string='Message', help="Optional message shown in their notification.")

    def action_invite(self):
        self.ensure_one()
        self.appointment_id._teleconsult_invite_colleagues(self.user_ids, note=self.note)
        return {'type': 'ir.actions.act_window_close'}
