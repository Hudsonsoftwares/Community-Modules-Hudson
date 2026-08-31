# -*- coding: utf-8 -*-
import ast
from odoo import api, fields, models

class HelpdeskManagementTeam(models.Model):
    _name = 'helpdesk.management.team'
    _description = 'Helpdesk Team'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'mail.alias.mixin', 'image.mixin']

    name = fields.Char(string='Team Name', required=True, translate=True)
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color Index')
    
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    
    # Assignment
    user_id = fields.Many2one('res.users', string='Team Leader')
    member_ids = fields.Many2many('res.users', string='Team Members')
    
    assignment_method = fields.Selection([
        ('random', 'Each user is assigned an equal number of tickets'),
        ('balanced', 'Each user has an equal number of open tickets'),
        ('tags', 'Dispatch tickets based on tags')
    ], string='Assignment Method', default='random', required=True)
    
    # Options
    use_alias = fields.Boolean(string='Email Alias')
    
    # Visibility & Assignment
    visibility_member_type = fields.Selection([
        ('internal', 'Invited internal users (private)'),
        ('company', 'All internal users (company)'),
        ('portal', 'Invited portal users and all internal users (public)')
    ], string='Visibility', default='portal')
    follower_ids = fields.Many2many('res.users', relation='helpdesk_team_follower_rel', column1='team_id', column2='user_id', string='Followers')
    auto_assignment = fields.Boolean('Automatic Assignment')
    
    # Channels
    use_livechat = fields.Boolean('Live Chat')
    
    # Help Center
    use_website_helpdesk_form = fields.Boolean('Website Form')
    website_id = fields.Many2one('website', string='Website')
    use_website_helpdesk_forum = fields.Boolean('Community Forum')
    forum_id = fields.Many2one('forum.forum', string='Forums')
    use_website_helpdesk_knowledge = fields.Boolean('Knowledge')
    article_id = fields.Many2one('knowledge.management.article', string='Article')
    use_website_helpdesk_elearning = fields.Boolean('eLearning')
    
    # Track & Bill Time
    use_helpdesk_timesheet = fields.Boolean('Timesheets')
    use_helpdesk_sale_timesheet = fields.Boolean('Time Billing')
    
    # Performance
    use_sla = fields.Boolean('SLA Policies')
    use_rating = fields.Boolean('Customer Ratings')
    resource_calendar_id = fields.Many2one('resource.calendar', 'Working Hours', default=lambda self: self.env.company.resource_calendar_id)
    # Self-Service
    
    # After Sales
    use_closure_by_customer = fields.Boolean('Closure by Customers')
    use_auto_close = fields.Boolean('Automatic Closing')
    auto_close_ticket_days = fields.Integer('After', default=7)
    auto_close_stage_id = fields.Many2one('helpdesk.management.stage', string='Move to Stage')
    auto_close_in_stage_ids = fields.Many2many('helpdesk.management.stage', relation='helpdesk_team_auto_close_stage_rel', column1='team_id', column2='stage_id', string='In Stages')
    use_auto_close_reminder = fields.Boolean('Auto-Close Reminder')
    auto_close_reminder_template_id = fields.Many2one('mail.template', string='Email Template', domain=[('model', '=', 'helpdesk.management.ticket')])
    auto_close_reminder_days = fields.Integer('Send', default=2)
    
    # After-Sales
    use_credit_notes = fields.Boolean('Refunds')
    use_coupons = fields.Boolean('Coupons')
    use_product_replacements = fields.Boolean('Replacements')
    use_fsm = fields.Boolean('Field Service')
    use_gift_cards = fields.Boolean('Gift Cards')
    use_product_returns = fields.Boolean('Returns')
    use_product_repairs = fields.Boolean('Repairs')
    
    ticket_ids = fields.One2many('helpdesk.management.ticket', 'team_id', string='Tickets')
    
    # Counts for dashboard
    ticket_count = fields.Integer(compute='_compute_ticket_count')
    open_ticket_count = fields.Integer(compute='_compute_ticket_count')
    unassigned_count = fields.Integer(compute='_compute_ticket_count')
    urgent_ticket_count = fields.Integer(compute='_compute_ticket_count')
    failed_ticket_count = fields.Integer(compute='_compute_ticket_count')
    closed_ticket_count = fields.Integer(compute='_compute_ticket_count')
    sla_success_rate = fields.Float(compute='_compute_ticket_metrics')
    average_rating = fields.Float(compute='_compute_ticket_metrics')
    sla_policy_count = fields.Integer(compute='_compute_sla_policy_count', string="SLA Policies Count")
    
    def _compute_sla_policy_count(self):
        for team in self:
            team.sla_policy_count = self.env['helpdesk.management.sla'].search_count([('team_id', '=', team.id)])

    def _compute_ticket_count(self):
        for team in self:
            team.ticket_count = 0
            team.open_ticket_count = 0
            team.unassigned_count = 0
            team.urgent_ticket_count = 0
            team.failed_ticket_count = 0
            team.closed_ticket_count = 0

        if not self.ids:
            return

        ticket_data = self.env['helpdesk.management.ticket'].read_group(
            [('team_id', 'in', self.ids)], 
            ['team_id', 'stage_id', 'user_id', 'priority', 'sla_status'], 
            ['team_id', 'stage_id', 'user_id', 'priority', 'sla_status'], lazy=False
        )
        
        # Pre-fetch stages to avoid looping queries
        stage_ids = [data.get('stage_id')[0] for data in ticket_data if data.get('stage_id')]
        stages = self.env['helpdesk.management.stage'].browse(list(set(stage_ids)))
        stage_is_close = {s.id: s.is_close for s in stages}

        for data in ticket_data:
            team_id = data.get('team_id')
            if not team_id: continue
            
            team = self.filtered(lambda t: t.id == team_id[0])
            if not team: continue
            
            count = data.get('__count', 0)
            team.ticket_count += count
            
            stage_id = data.get('stage_id')
            is_close = stage_is_close.get(stage_id[0], False) if stage_id else False
            
            if is_close:
                team.closed_ticket_count += count
            else:
                team.open_ticket_count += count
                if not data.get('user_id'):
                    team.unassigned_count += count
                if data.get('priority') == '3':
                    team.urgent_ticket_count += count
                if data.get('sla_status') == 'breached':
                    team.failed_ticket_count += count

    def _compute_ticket_metrics(self):
        for team in self:
            team.sla_success_rate = 0.0
            team.average_rating = 0.0

        if not self.ids:
            return

        for team in self:
            # Calculate SLA Success Rate
            closed_tickets = self.env['helpdesk.management.ticket'].search([
                ('team_id', '=', team.id),
                ('stage_id.is_close', '=', True)
            ])
            if closed_tickets:
                achieved = len(closed_tickets.filtered(lambda t: t.sla_status == 'achieved'))
                team.sla_success_rate = round((achieved / len(closed_tickets)) * 100, 2)
            
            # Calculate Average Rating
            tickets_with_ratings = closed_tickets.filtered(lambda t: t.average_rating > 0)
            if tickets_with_ratings:
                total_rating = sum(t.average_rating for t in tickets_with_ratings)
                team.average_rating = round(total_rating / len(tickets_with_ratings), 1)

    @api.model
    def get_dashboard_metrics(self):
        ticket_model = self.env['helpdesk.management.ticket']
        
        # All Open Tickets stats (handle tickets without stages as open)
        domain_open = ['|', ('stage_id', '=', False), ('stage_id.is_close', '=', False)]
        my_tickets = ticket_model.search(domain_open)
        my_open_count = len(my_tickets)
        my_high_priority_tickets = my_tickets.filtered(lambda t: t.priority == '2')
        my_high_priority = len(my_high_priority_tickets)
        my_urgent_tickets = my_tickets.filtered(lambda t: t.priority == '3')
        my_urgent = len(my_urgent_tickets)
        my_failed = len(my_tickets.filtered(lambda t: t.sla_status == 'breached'))
        
        # Avg open hours
        import datetime
        now = fields.Datetime.now()
        open_hours = 0
        if my_open_count > 0:
            total_seconds = sum((now - t.create_date).total_seconds() for t in my_tickets if t.create_date)
            open_hours = round(total_seconds / 3600 / my_open_count, 1)
            
        hp_open_hours = 0
        if my_high_priority > 0:
            hp_total_seconds = sum((now - t.create_date).total_seconds() for t in my_high_priority_tickets if t.create_date)
            hp_open_hours = round(hp_total_seconds / 3600 / my_high_priority, 1)
            
        urg_open_hours = 0
        if my_urgent > 0:
            urg_total_seconds = sum((now - t.create_date).total_seconds() for t in my_urgent_tickets if t.create_date)
            urg_open_hours = round(urg_total_seconds / 3600 / my_urgent, 1)
            
        hp_failed = len(my_high_priority_tickets.filtered(lambda t: t.sla_status == 'breached'))
        urg_failed = len(my_urgent_tickets.filtered(lambda t: t.sla_status == 'breached'))
            
        # Overall Performance stats
        domain_closed = [('stage_id', '!=', False), ('stage_id.is_close', '=', True)]
        my_closed_tickets = ticket_model.search(domain_closed)
        my_closed = len(my_closed_tickets)

        
        # SLA Success Rate (for closed tickets)
        if my_closed > 0:
            achieved = len(my_closed_tickets.filtered(lambda t: t.sla_status == 'achieved'))
            sla_success_rate = round((achieved / my_closed) * 100)
        else:
            sla_success_rate = 100
            
        # Average Rating
        rated_closed_tickets = my_closed_tickets.filtered(lambda t: t.average_rating > 0)
        if rated_closed_tickets:
            avg_rating = sum(t.average_rating for t in rated_closed_tickets) / len(rated_closed_tickets)
            avg_rating = int(round(avg_rating, 0))
        else:
            avg_rating = 0
            
        # Today closed
        today = fields.Datetime.now().replace(hour=0, minute=0, second=0)
        today_closed = len(my_closed_tickets.filtered(lambda t: (t.close_date or t.write_date) >= today))
        
        # Avg Last 7 days
        last_7_days = today - datetime.timedelta(days=7)
        last_7_closed_tickets = my_closed_tickets.filtered(lambda t: (t.close_date or t.write_date) >= last_7_days)
        last_7_closed = len(last_7_closed_tickets)
        avg_last_7 = round(last_7_closed / 7.0, 1)
        
        # 7d SLA Success Rate
        if last_7_closed > 0:
            achieved_7d = len(last_7_closed_tickets.filtered(lambda t: t.sla_status == 'achieved'))
            sla_success_rate_7d = round((achieved_7d / last_7_closed) * 100)
        else:
            sla_success_rate_7d = 100
            
        # 7d Average Rating
        last_7_rated_tickets = last_7_closed_tickets.filtered(lambda t: t.average_rating > 0)
        if last_7_rated_tickets:
            avg_rating_7d = sum(t.average_rating for t in last_7_rated_tickets) / len(last_7_rated_tickets)
            avg_rating_7d = int(round(avg_rating_7d, 0))
        else:
            avg_rating_7d = 0
        
        return {
            'my_tickets': my_open_count,
            'high_priority': my_high_priority,
            'urgent': my_urgent,
            'open_tickets': my_open_count,
            'avg_open_hours': f"{open_hours}h",
            'hp_avg_open_hours': f"{hp_open_hours}h",
            'urg_avg_open_hours': f"{urg_open_hours}h",
            'failed_tickets': my_failed,
            'hp_failed_tickets': hp_failed,
            'urg_failed_tickets': urg_failed,
            
            'closed_tickets': my_closed,
            'sla_success_rate': f"{sla_success_rate}%",
            'sla_success_rate_7d': f"{sla_success_rate_7d}%",
            'average_rating': f"{avg_rating}",
            'average_rating_7d': f"{avg_rating_7d}",
            'today': today_closed,
            'avg_last_7_days': avg_last_7
        }

    def _alias_get_creation_values(self):
        values = super(HelpdeskManagementTeam, self)._alias_get_creation_values()
        values['alias_model_id'] = self.env['ir.model']._get('helpdesk.management.ticket').id
        if self.id:
            values['alias_defaults'] = defaults = ast.literal_eval(self.alias_defaults or "{}")
            defaults['team_id'] = self.id
        return values
