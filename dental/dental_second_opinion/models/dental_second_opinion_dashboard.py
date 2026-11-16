# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import models, fields, api

from .dental_second_opinion import OPEN_STATES, STATES


class DentalSecondOpinionDashboard(models.AbstractModel):
    _name = 'dental.second.opinion.dashboard'
    _description = 'Second Opinion Dashboard'

    @api.model
    def get_dashboard_data(self):
        """Counts and queues for the current user. Every search runs with the user's own access rights,
        so a specialist only sees requests assigned to them in their selected branches."""
        Request = self.env['dental.second.opinion']
        uid = self.env.uid
        mine = [('specialist_user_id', '=', uid)]
        sent = [('requesting_user_id', '=', uid)]
        since = fields.Datetime.now() - timedelta(days=30)

        def count(domain):
            return Request.search_count(domain)

        def rows(domain, limit=8):
            return [{
                'id': r.id,
                'name': r.name,
                'patient': r.patient_id.name or '',
                'case': r.case_id.name or '',
                'counterpart': (r.requesting_doctor_id.name or r.requesting_user_id.name)
                if r.specialist_user_id.id == uid else (r.specialist_id.name or ''),
                'priority': r.priority,
                'state': r.state,
                'state_label': dict(STATES)[r.state],
                'due_date': fields.Date.to_string(r.due_date) if r.due_date else '',
                'is_overdue': r.is_overdue,
            } for r in Request.search(domain, limit=limit, order='priority desc, due_date asc, id desc')]

        completed = Request.search(mine + [('opinion_date', '>=', since)])
        turnaround = completed.mapped('turnaround_hours')
        return {
            'is_specialist': self.env.user.has_group('dental_second_opinion.group_dental_specialist'),
            'is_manager': self.env.user.has_group('dental_base.group_dental_manager'),
            'specialist': {
                'new': count(mine + [('state', '=', 'submitted')]),
                'in_review': count(mine + [('state', '=', 'in_review')]),
                'clarification': count(mine + [('state', '=', 'clarification')]),
                'waiting_dentist': count(mine + [('state', 'in', ('info_requested', 'opinion_submitted'))]),
                'overdue': count(mine + [('is_overdue', '=', True)]),
                'done_30d': len(completed),
                'avg_turnaround': round(sum(turnaround) / len(turnaround), 1) if turnaround else 0.0,
                'queue': rows(mine + [('state', 'in', ('submitted', 'in_review', 'clarification'))]),
            },
            'requester': {
                'open': count(sent + [('state', 'in', OPEN_STATES)]),
                'to_decide': count(sent + [('state', '=', 'opinion_submitted')]),
                'info_requested': count(sent + [('state', '=', 'info_requested')]),
                'declined': count(sent + [('state', '=', 'declined')]),
                'queue': rows(sent + [('state', 'in', ('opinion_submitted', 'info_requested', 'declined'))]),
            },
            'clinic': {
                'open': count([('state', 'in', OPEN_STATES)]),
                'overdue': count([('is_overdue', '=', True)]),
                'emergency': count([('state', 'in', OPEN_STATES), ('priority', '=', '2')]),
            },
        }
