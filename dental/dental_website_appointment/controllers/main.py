# -*- coding: utf-8 -*-
import logging
import sys
import importlib
from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)


def _ensure_dental_appointment_methods():
    """Ensure runtime model class across all active registries has all centralized scheduling methods attached."""
    try:
        mod_name = 'odoo.addons.dental_appointment.models.appointment'
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])
        else:
            __import__(mod_name)
        from odoo.addons.dental_appointment.models.appointment import DentalAppointment
        from odoo.orm.registry import Registry

        attrs = ['check_patient', 'get_available_slots', 'match_or_create_patient', 'create_appointment_booking']

        for reg in list(getattr(Registry, 'registries', {}).values()):
            if 'dental.appointment' in reg:
                m = reg['dental.appointment']
                for c in {m, m.__class__, type(m)}:
                    for attr in attrs:
                        method = getattr(DentalAppointment, attr, None)
                        if method:
                            setattr(c, attr, method)

        if request and hasattr(request, 'env') and 'dental.appointment' in request.env:
            appt_model = request.env['dental.appointment']
            for c in {appt_model, appt_model.__class__, type(appt_model)}:
                for attr in attrs:
                    method = getattr(DentalAppointment, attr, None)
                    if method:
                        setattr(c, attr, method)
    except Exception as e:
        _logger.warning("Could not dynamically bind dental.appointment methods: %s", e)


class DentalWebsiteAppointmentController(http.Controller):

    @http.route(['/book-appointment', '/appointment'], type='http', auth='public', website=True, sitemap=True)
    def book_appointment_page(self, **kwargs):
        """Render the 6-step modern animated dental booking page."""
        _ensure_dental_appointment_methods()
        dentists = request.env['hr.employee'].sudo().search([
            ('is_dentist', '=', True),
            ('active', '=', True),
        ], order='id asc')
        if not dentists:
            dentists = request.env['hr.employee'].sudo().search([
                ('id', 'in', [1, 4])
            ], order='id asc')

        appointment_types = request.env['dental.appointment.type'].sudo().search([
            ('active', '=', True),
        ], order='id asc')

        treatments = request.env['product.template'].sudo().search([
            ('is_dental_treatment', '=', True),
        ], order='sequence asc, name asc')

        branches = request.env['res.company'].sudo().search([])

        values = {
            'dentists': dentists,
            'all_dentists': dentists,
            'appointment_types': appointment_types,
            'treatments': treatments,
            'branches': branches,
            'default_branch': request.env.company,
        }
        try:
            return request.render('dental_website_appointment.book_appointment', values)
        except Exception:
            return request.render('dental_appointment.book_appointment', values)

    @http.route(['/dental/check_patient', '/website/action/check_patient'], type='json', auth='public', methods=['POST'], csrf=False)
    def check_patient(self, identifier=None, **kwargs):
        """Search for an existing patient by phone number, email, or patient ID via dental.appointment model."""
        _ensure_dental_appointment_methods()
        target_id = identifier or request.params.get('identifier')
        return request.env['dental.appointment'].sudo().check_patient(identifier=target_id)

    @http.route(['/dental/get_slots', '/website/action/get_slots'], type='json', auth='public', methods=['POST'], csrf=False)
    def get_available_slots(self, date=None, doctor_id=None, duration=30, branch_id=None, **kwargs):
        """Return available time slots for a given date, doctor, and duration via dental.appointment model."""
        _ensure_dental_appointment_methods()
        params = request.params or {}
        target_date = date or params.get('date')
        target_doctor = doctor_id if doctor_id is not None else params.get('doctor_id')
        target_duration = duration if duration is not None else params.get('duration')
        target_branch = branch_id if branch_id is not None else params.get('branch_id')
        return request.env['dental.appointment'].sudo().get_available_slots(
            date=target_date,
            doctor_id=target_doctor,
            duration=target_duration,
            branch_id=target_branch,
            **kwargs
        )

    @http.route([
        '/dental/book_appointment',
        '/dental/submit_appointment',
        '/website/action/book_appointment'
    ], type='json', auth='public', methods=['POST'], csrf=False)
    def book_appointment_submit(self, **post):
        """Handle appointment creation using the centralized dental.appointment booking engine."""
        _ensure_dental_appointment_methods()
        data = dict(post or {})
        if request.params:
            for k, v in request.params.items():
                if k not in data or not data[k]:
                    data[k] = v
        return request.env['dental.appointment'].sudo().create_appointment_booking(data)
