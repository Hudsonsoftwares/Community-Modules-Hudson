# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class HelpdeskManagementTicket(models.Model):
    _name = 'helpdesk.management.ticket'
    _description = 'Helpdesk Ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, create_date desc'

    name = fields.Char(string='Ticket Number', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    subject = fields.Char(string='Subject', required=True, tracking=True)
    access_token = fields.Char('Security Token', copy=False, default=lambda self: str(__import__('uuid').uuid4()))
    
    # Customer Info
    partner_id = fields.Many2one('res.partner', string='Customer', tracking=True)
    partner_name = fields.Char(string='Customer Name')
    partner_email = fields.Char(string='Customer Email')
    partner_phone = fields.Char(string='Customer Phone')
    
    # Assignment
    team_id = fields.Many2one('helpdesk.management.team', string='Team', tracking=True, index=True)
    user_id = fields.Many2one('res.users', string='Assigned to', tracking=True, index=True)
    
    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id:
            if self.partner_id.name and not self.partner_name:
                self.partner_name = self.partner_id.name
            if self.partner_id.email and not self.partner_email:
                self.partner_email = self.partner_id.email
            if self.partner_id.phone and not self.partner_phone:
                self.partner_phone = self.partner_id.phone
            elif self.partner_id.mobile and not self.partner_phone:
                self.partner_phone = self.partner_id.mobile
    
    # Status
    stage_id = fields.Many2one('helpdesk.management.stage', string='Stage', tracking=True,
                               group_expand='_read_group_stage_ids', copy=False,
                               index=True, ondelete='restrict')
    
    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Normal'),
        ('2', 'High'),
        ('3', 'Urgent')
    ], string='Priority', default='0', tracking=True)
    
    # Dates
    assign_date = fields.Datetime(string='Assign Date')
    close_date = fields.Datetime(string='Close Date')
    
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color Index')

    # Categorization
    description = fields.Html(string='Description', tracking=True)
    tag_ids = fields.Many2many('helpdesk.management.tag', string='Tags')
    ticket_type_id = fields.Many2one('helpdesk.management.ticket.type', string='Ticket Type', tracking=True)
    category_id = fields.Many2one('helpdesk.management.category', string='Category', tracking=True)
    source_id = fields.Many2one('helpdesk.management.source', string='Source', tracking=True)
    
    # After Sales (Related to Team)
    use_credit_notes = fields.Boolean(related='team_id.use_credit_notes')
    use_gift_cards = fields.Boolean(related='team_id.use_gift_cards')
    use_coupons = fields.Boolean(related='team_id.use_coupons')
    use_product_returns = fields.Boolean(related='team_id.use_product_returns')
    use_product_replacements = fields.Boolean(related='team_id.use_product_replacements')
    use_product_repairs = fields.Boolean(related='team_id.use_product_repairs')
    
    def action_open_refund_wizard(self):
        self.ensure_one()
        return {
            'name': _('Refund'),
            'type': 'ir.actions.act_window',
            'res_model': 'helpdesk.ticket.refund',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_ticket_id': self.id}
        }
        
    def action_open_gift_card_wizard(self):
        self.ensure_one()
        return {
            'name': _('Generate & Send Gift Card'),
            'type': 'ir.actions.act_window',
            'res_model': 'helpdesk.ticket.giftcard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_ticket_id': self.id}
        }
        
    def action_open_coupon_wizard(self):
        self.ensure_one()
        return {
            'name': _('Generate a Coupon'),
            'type': 'ir.actions.act_window',
            'res_model': 'helpdesk.ticket.coupon',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_ticket_id': self.id}
        }
        
    def action_return(self):
        self.ensure_one()
        return {
            'name': _('Return'),
            'type': 'ir.actions.act_window',
            'res_model': 'helpdesk.ticket.return',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_ticket_id': self.id}
        }
        
    def action_replace(self):
        self.ensure_one()
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'outgoing'),
            ('company_id', '=', self.company_id.id or self.env.company.id)
        ], limit=1)
        return {
            'name': _('New Delivery'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_picking_type_id': picking_type.id,
                'default_origin': f'Ticket: {self.name}',
            }
        }
        
    def action_repair(self):
        self.ensure_one()
        return {
            'name': _('New Repair'),
            'type': 'ir.actions.act_window',
            'res_model': 'repair.order',
            'view_mode': 'form',
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_company_id': self.company_id.id,
            }
        }

    def action_plan_intervention(self):
        self.ensure_one()
        import logging
        _logger = logging.getLogger(__name__)
        _logger.info("========= PLAN INTERVENTION BUTTON CLICKED =========")
        return {
            'name': _('Plan Intervention'),
            'type': 'ir.actions.act_window',
            'res_model': 'project.task',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_name': f'Intervention for: {self.name}',
                'default_helpdesk_ticket_id': self.id,
            }
        }
        
    def action_create_fsm_order(self):
        self.ensure_one()
        return {
            'name': _('Create Field Service'),
            'type': 'ir.actions.act_window',
            'res_model': 'field.service.order',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {
                'default_partner_id': self.partner_id.id,
                'default_title': f'Service for: {self.name}',
                'default_helpdesk_ticket_id': self.id,
            }
        }
        
    def action_view_tasks(self):
        self.ensure_one()
        return {
            'name': _('Tasks'),
            'type': 'ir.actions.act_window',
            'res_model': 'project.task',
            'view_mode': 'list,form',
            'domain': [('helpdesk_ticket_id', '=', self.id)],
            'context': {'default_helpdesk_ticket_id': self.id},
        }

    def action_view_fsm_orders(self):
        self.ensure_one()
        return {
            'name': _('Field Service Orders'),
            'type': 'ir.actions.act_window',
            'res_model': 'field.service.order',
            'view_mode': 'list,form',
            'domain': [('helpdesk_ticket_id', '=', self.id)],
            'context': {'default_helpdesk_ticket_id': self.id},
        }

    # Integrations
    task_ids = fields.One2many('project.task', 'helpdesk_ticket_id', string='Tasks')
    task_count = fields.Integer(compute='_compute_task_count')
    fsm_order_ids = fields.One2many('field.service.order', 'helpdesk_ticket_id', string='Field Service Orders')
    fsm_order_count = fields.Integer(compute='_compute_fsm_order_count')
    
    @api.depends('task_ids')
    def _compute_task_count(self):
        for ticket in self:
            ticket.task_count = len(ticket.task_ids)
            
    @api.depends('fsm_order_ids')
    def _compute_fsm_order_count(self):
        for ticket in self:
            ticket.fsm_order_count = len(ticket.fsm_order_ids)

    
    # SLA
    sla_id = fields.Many2one('helpdesk.management.sla', string='SLA Policy', tracking=True)
    sla_deadline = fields.Datetime(string='SLA Deadline', tracking=True)
    sla_status = fields.Selection([
        ('on_track', 'On Track'),
        ('warning', 'Warning'),
        ('breached', 'Breached'),
        ('achieved', 'Achieved')
    ], string='SLA Status', compute='_compute_sla_status', store=True, tracking=True)

    @api.depends('sla_deadline', 'stage_id', 'stage_id.is_close')
    def _compute_sla_status(self):
        now = fields.Datetime.now()
        for ticket in self:
            if not ticket.sla_deadline:
                ticket.sla_status = False
                continue
                
            if ticket.stage_id and ticket.stage_id.is_close:
                if ticket.sla_status != 'breached':
                    ticket.sla_status = 'achieved'
                continue
                
            if now > ticket.sla_deadline:
                ticket.sla_status = 'breached'
            elif (ticket.sla_deadline - now).total_seconds() < 3600: # 1 hour warning
                ticket.sla_status = 'warning'
            else:
                ticket.sla_status = 'on_track'

    # Time Tracking & Rating
    time_ids = fields.One2many('helpdesk.management.ticket.time', 'ticket_id', string='Timesheets')
    total_time = fields.Float(string='Total Time', compute='_compute_total_time')
    ticket_rating_ids = fields.One2many('helpdesk.management.ticket.rating', 'ticket_id', string='Ratings')
    average_rating = fields.Float(string='Average Rating', compute='_compute_average_rating')

    @api.depends('time_ids.duration')
    def _compute_total_time(self):
        for ticket in self:
            ticket.total_time = sum(ticket.time_ids.mapped('duration'))

    @api.depends('ticket_rating_ids.rating')
    def _compute_average_rating(self):
        for ticket in self:
            ratings = [int(r.rating) for r in ticket.ticket_rating_ids if r.rating]
            ticket.average_rating = sum(ratings) / len(ratings) if ratings else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        import random
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('helpdesk.management.ticket') or _('New')
            
            if not vals.get('user_id') and vals.get('team_id'):
                team = self.env['helpdesk.management.team'].browse(vals['team_id'])
                if team.auto_assignment and team.member_ids:
                    if team.assignment_method == 'random':
                        vals['user_id'] = random.choice(team.member_ids).id
                    elif team.assignment_method == 'balanced':
                        user_counts = self.env['helpdesk.management.ticket'].read_group(
                            [('team_id', '=', team.id), ('stage_id.is_close', '=', False), ('user_id', 'in', team.member_ids.ids)],
                            ['user_id'], ['user_id']
                        )
                        count_dict = {res['user_id'][0]: res['user_id_count'] for res in user_counts if res.get('user_id')}
                        best_user = min(team.member_ids, key=lambda u: count_dict.get(u.id, 0))
                        vals['user_id'] = best_user.id
                    elif team.assignment_method == 'tags':
                        vals['user_id'] = random.choice(team.member_ids).id

        tickets = super().create(vals_list)
        
        for ticket in tickets:
            template = self.env.ref('helpdesk_management_pro.mail_template_ticket_receipt', raise_if_not_found=False)
            if template:
                template.send_mail(ticket.id, force_send=True)
                
        return tickets

    @api.model
    def _read_group_stage_ids(self, stages, domain, order):
        search_domain = []
        if self._context.get('default_team_id'):
            search_domain = ['|', ('team_ids', '=', False), ('team_ids', 'in', [self._context['default_team_id']])]
        return stages.search(search_domain, order=order)

    def write(self, vals):
        if 'stage_id' in vals:
            stage = self.env['helpdesk.management.stage'].browse(vals['stage_id'])
            if stage.is_close:
                vals['close_date'] = fields.Datetime.now()
            else:
                vals['close_date'] = False
                
        res = super(HelpdeskManagementTicket, self).write(vals)
        
        if 'stage_id' in vals:
            for ticket in self:
                if ticket.stage_id and ticket.stage_id.template_id:
                    ticket.stage_id.template_id.send_mail(ticket.id, force_send=True)
        return res

    def action_reply(self):
        self.ensure_one()
        return {
            'name': _('Reply'),
            'type': 'ir.actions.act_window',
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_model': 'helpdesk.management.ticket',
                'default_res_id': self.id,
                'default_use_template': False,
                'force_email': True,
                'default_partner_ids': self.partner_id.ids if self.partner_id else []
            },
        }


    def message_new(self, msg_dict, custom_values=None):
        """ Overrides mail_thread message_new to route incoming emails to tickets """
        custom_values = custom_values or {}
        if not custom_values.get('team_id') and self.env.context.get('default_team_id'):
            custom_values['team_id'] = self.env.context.get('default_team_id')
        return super(HelpdeskManagementTicket, self).message_new(msg_dict, custom_values)

    @api.model
    def create_ticket_from_livechat(self, chat_data):
        """ Hook for Live Chat integration to create tickets """
        return self.create({
            'subject': 'Livechat Ticket',
            'description': chat_data.get('transcript', ''),
            'partner_id': chat_data.get('partner_id'),
        })

    @api.model
    def create_ticket_from_whatsapp(self, wa_data):
        """ Hook for WhatsApp integration to create tickets """
        return self.create({
            'subject': 'WhatsApp Ticket',
            'description': wa_data.get('message', ''),
            'partner_phone': wa_data.get('phone'),
        })
