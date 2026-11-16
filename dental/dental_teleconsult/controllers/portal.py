# -*- coding: utf-8 -*-
from odoo import fields, http
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal


class TeleconsultPortal(CustomerPortal):
    """'My Online Consultations' for patients (and guardians) with a portal account."""

    def _teleconsult_portal_domain(self):
        partner = request.env.user.partner_id
        return [
            ('consultation_mode', '=', 'online'),
            ('patient_id', 'in', (partner | partner.child_ids).ids),
            ('state', 'in', ('confirmed', 'checked_in', 'in_consultation', 'completed')),
        ]

    def _prepare_portal_counter_values(self, counter):
        if counter == 'teleconsult_count':
            return 'dental.appointment', self._teleconsult_portal_domain(), 'sudo'
        return super()._prepare_portal_counter_values(counter)

    @http.route('/my/teleconsultations', type='http', auth='user', website=True)
    def portal_my_teleconsultations(self, **kwargs):
        # sudo: dental.appointment - restricted to the logged-in patient's own visits by the domain
        appointments = request.env['dental.appointment'].sudo().search(
            self._teleconsult_portal_domain(), order='date_start desc', limit=80)
        values = self._prepare_portal_layout_values()
        values.update({
            'appointments': appointments,
            'page_name': 'teleconsultations',
            'now': fields.Datetime.now(),
        })
        return request.render('dental_teleconsult.portal_my_teleconsultations', values)
