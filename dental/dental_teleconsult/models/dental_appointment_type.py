# -*- coding: utf-8 -*-
from odoo import fields, models


class DentalAppointmentType(models.Model):
    _inherit = 'dental.appointment.type'

    allow_online = fields.Boolean(
        string='Available Online', default=True,
        help="Appointments of this type may be held as an online video consultation.")
