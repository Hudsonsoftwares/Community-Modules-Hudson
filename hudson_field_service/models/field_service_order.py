# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from datetime import timedelta
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class FieldServiceOrder(models.Model):
    _name = 'field.service.order'
    _description = 'Field Service Order'
    _inherit = ['portal.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, date_planned asc, id desc'

    # -------------------------------------------------------------------------
    # FIELDS
    # -------------------------------------------------------------------------

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
        index='trigram',
    )
    title = fields.Char(string='Title', required=True, tracking=True)
    description = fields.Html(string='Description', sanitize_attributes=False)
    active = fields.Boolean(default=True)

    # Stage & State
    stage_id = fields.Many2one(
        'field.service.stage',
        string='Stage',
        tracking=True,
        index=True,
        default=lambda self: self._default_stage_id(),
        group_expand='_read_group_stage_ids',
        ondelete='restrict',
    )
    state = fields.Selection([
        ('new', 'New'),
        ('scheduled', 'Scheduled'),
        ('in_progress', 'In Progress'),
        ('paused', 'Paused'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='new', required=True, tracking=True, copy=False)
    priority = fields.Selection([
        ('0', 'Normal'),
        ('1', 'Low'),
        ('2', 'High'),
        ('3', 'Urgent'),
    ], default='0', string='Priority', tracking=True)
    color = fields.Integer(string='Color Index')

    # Project Integration (Optional)
    project_id = fields.Many2one(
        'project.project',
        string='Project',
        tracking=True,
        help='Optional: Link this field service order to a project.',
    )
    task_id = fields.Many2one(
        'project.task',
        string='Project Task',
        tracking=True,
        domain="[('project_id', '=?', project_id)]",
        help='Optional: Link this field service order to a specific project task.',
    )

    # Customer
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        tracking=True,
        index=True,
    )
    partner_phone = fields.Char(
        string='Phone',
        compute='_compute_partner_info',
        store=True,
        readonly=False,
    )
    partner_email = fields.Char(
        string='Email',
        compute='_compute_partner_info',
        store=True,
        readonly=False,
    )
    partner_address = fields.Char(
        string='Service Address',
        compute='_compute_partner_info',
        store=True,
        readonly=False,
        help='Location where the service will be performed.',
    )

    employee_id = fields.Many2one(
        'hr.employee',
        string='Primary Technician',
        tracking=True,
        index=True,
        group_expand='_read_group_employee_ids',
        default=lambda self: self.env.user.employee_id,
    )
    extra_employee_ids = fields.Many2many(
        'hr.employee',
        'field_service_order_extra_employees_rel',
        'order_id',
        'employee_id',
        string='Extra Assignees',
        tracking=True,
        help="Additional technicians assigned to this job.",
    )
    team_leader_employee_id = fields.Many2one(
        'hr.employee',
        string='Team Leader',
        tracking=True,
    )

    # Scheduling
    date_planned = fields.Datetime(
        string='Planned Date',
        tracking=True,
        index=True,
    )
    date_deadline = fields.Date(
        string='Deadline',
        tracking=True,
    )
    duration_planned = fields.Float(
        string='Total Scheduled Time (Hours)',
        help='Estimated total duration from start to finish.',
    )
    rest_time_planned = fields.Float(
        string='Planned Rest Time (Hours)',
        help='Expected rest or non-working time during the shift.',
        default=0.0,
    )
    duration_working_planned = fields.Float(
        string='Planned Working Time (Hours)',
        compute='_compute_duration_working',
        store=True,
        help='Total scheduled time minus planned rest time.',
    )

    # Timer & Actual Duration
    date_start = fields.Datetime(string='Actual Start', readonly=True, copy=False)
    date_end = fields.Datetime(string='Actual End', readonly=True, copy=False)
    timer_start = fields.Datetime(
        string='Timer Started At',
        readonly=True,
        copy=False,
        help='Timestamp when the current timer session was started.',
    )
    is_timer_running = fields.Boolean(
        string='Timer Running',
        compute='_compute_is_timer_running',
        store=False,
    )
    last_paused_time = fields.Datetime(
        string='Last Paused Time',
        readonly=True,
        copy=False,
        help='Timestamp when the order was last paused.',
    )
    rest_time_actual = fields.Float(
        string='Actual Rest Time (Hours)',
        readonly=True,
        copy=False,
        default=0.0,
        help='Total accumulated time spent in paused state.',
    )
    start_latitude = fields.Float(string='Start Latitude', digits=(16, 5), copy=False)
    start_longitude = fields.Float(string='Start Longitude', digits=(16, 5), copy=False)
    duration_actual = fields.Float(
        string='Actual Duration (Hours)',
        compute='_compute_duration_actual',
        store=True,
        help='Total time spent from all timesheet entries.',
    )

    # Live Location (updated in real-time by technician's device)
    current_latitude = fields.Float(
        string='Current Latitude',
        digits=(16, 5),
        copy=False,
        help='Most recent GPS latitude reported by the technician\'s device.',
    )
    current_longitude = fields.Float(
        string='Current Longitude',
        digits=(16, 5),
        copy=False,
        help='Most recent GPS longitude reported by the technician\'s device.',
    )
    last_location_update = fields.Datetime(
        string='Location Last Updated',
        readonly=True,
        copy=False,
    )

    # Timesheets
    timesheet_ids = fields.One2many(
        'field.service.timesheet',
        'order_id',
        string='Time Entries',
    )
    total_time_spent = fields.Float(
        string='Total Time Spent',
        compute='_compute_duration_actual',
        store=True,
    )
    timesheet_count = fields.Integer(
        string='Timesheet Count',
        compute='_compute_timesheet_count',
    )

    # Products
    product_line_ids = fields.One2many(
        'field.service.product.line',
        'order_id',
        string='Products Used',
    )
    image_ids = fields.Many2many(
        'ir.attachment',
        string="Images",
        help="Upload images related to this service order."
    )
    service_image_ids = fields.One2many(
        'field.service.image',
        'order_id',
        string='Service Images'
    )
    total_products_amount = fields.Float(
        string='Products Total',
        compute='_compute_total_products_amount',
        store=True,
        digits='Product Price',
    )

    # Invoice & Sale Order
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sales Order',
        tracking=True,
        copy=False,
    )
    sale_order_count = fields.Integer(
        string='Sale Orders',
        compute='_compute_sale_order_count',
    )
    invoice_id = fields.Many2one(
        'account.move',
        string='Invoice',
        tracking=True,
        copy=False,
        readonly=True,
    )
    invoice_status = fields.Selection([
        ('not_invoiced', 'Not Invoiced'),
        ('invoiced', 'Invoiced'),
    ], string='Invoice Status', default='not_invoiced', compute='_compute_invoice_status', store=True)

    # Tags
    tag_ids = fields.Many2many(
        'field.service.tag',
        string='Tags',
    )

    # Company
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )

    # Worksheet & Signature
    notes = fields.Text(string='Internal Notes')
    worksheet_notes = fields.Html(
        string='Work Performed',
        sanitize_attributes=False,
        help='Details of the work performed during the service visit.',
    )
    customer_signature = fields.Binary(
        string='Customer Signature',
        copy=False,
    )
    customer_signed_by = fields.Char(
        string='Signed By',
        copy=False,
    )
    customer_signed_date = fields.Datetime(
        string='Signed Date',
        copy=False,
    )

    # Customer Rating (stored directly on the order)
    customer_rating = fields.Selection([
        ('1', '😞 Poor'),
        ('2', '😐 Below Average'),
        ('3', '🙂 Average'),
        ('4', '😊 Good'),
        ('5', '😁 Excellent'),
    ], string='Customer Rating', copy=False, tracking=True)
    rating_note = fields.Text(
        string='Rating Notes',
        copy=False,
        help='Additional feedback from the customer.',
    )
    survey_input_id = fields.Many2one(
        'survey.user_input',
        string='Survey Response',
        readonly=True,
        copy=False,
        help='The survey invitation sent to the customer upon order completion.',
    )
    is_published = fields.Boolean(
        string="Published", default=False, tracking=True,
        help="If true, the shift is published and visible to the technician."
    )

    # Computed display fields
    total_amount = fields.Float(
        string='Total Amount',
        compute='_compute_total_amount',
        store=True,
        digits='Product Price',
    )
    hourly_rate = fields.Float(
        string='Hourly Rate',
        compute='_compute_hourly_rate',
        store=False,
    )

    # -------------------------------------------------------------------------
    # DEFAULT METHODS
    # -------------------------------------------------------------------------

    def _default_stage_id(self):
        return self.env['field.service.stage'].search([], order='sequence, id', limit=1)

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        """Always show all stages in Kanban view."""
        return self.env['field.service.stage'].search([])

    @api.model
    def _read_group_employee_ids(self, employees, domain):
        """Always show all active employees in Kanban view."""
        return self.env['hr.employee'].search([])

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends('partner_id')
    def _compute_partner_info(self):
        for order in self:
            if order.partner_id:
                order.partner_phone = order.partner_id.phone
                order.partner_email = order.partner_id.email
                order.partner_address = order.partner_id.contact_address
            else:
                order.partner_phone = False
                order.partner_email = False
                order.partner_address = False

    def _compute_access_url(self):
        super()._compute_access_url()
        for order in self:
            order.access_url = f'/my/field_service/{order.id}'

    @api.depends('timer_start')
    def _compute_is_timer_running(self):
        for order in self:
            order.is_timer_running = bool(order.timer_start)

    @api.depends('duration_planned', 'rest_time_planned')
    def _compute_duration_working(self):
        for order in self:
            order.duration_working_planned = max(0.0, order.duration_planned - order.rest_time_planned)

    @api.depends('timesheet_ids.duration')
    def _compute_duration_actual(self):
        for order in self:
            total = sum(order.timesheet_ids.mapped('duration'))
            order.duration_actual = total
            order.total_time_spent = total

    @api.depends('timesheet_ids')
    def _compute_timesheet_count(self):
        for order in self:
            order.timesheet_count = len(order.timesheet_ids)

    @api.depends('product_line_ids.price_subtotal')
    def _compute_total_products_amount(self):
        for order in self:
            order.total_products_amount = sum(order.product_line_ids.mapped('price_subtotal'))

    @api.depends('sale_order_id')
    def _compute_sale_order_count(self):
        for order in self:
            order.sale_order_count = 1 if order.sale_order_id else 0

    @api.depends('invoice_id', 'invoice_id.state', 'sale_order_id', 'sale_order_id.invoice_status')
    def _compute_invoice_status(self):
        for order in self:
            # Priority: check direct invoice first
            if order.invoice_id and order.invoice_id.state != 'cancel':
                order.invoice_status = 'invoiced'
            # Then check whether the linked SO is fully or partially invoiced
            elif (order.sale_order_id
                  and order.sale_order_id.invoice_status in ('invoiced', 'full')):
                order.invoice_status = 'invoiced'
                # Auto-link the first posted SO invoice so "View Invoice" works
                so_invoices = order.sale_order_id.invoice_ids.filtered(
                    lambda i: i.state not in ('cancel', 'draft')
                    and i.move_type == 'out_invoice'
                )
                if so_invoices and not order.invoice_id:
                    order.invoice_id = so_invoices[0]
            else:
                order.invoice_status = 'not_invoiced'

    def _compute_hourly_rate(self):
        default_rate = self.env['ir.config_parameter'].sudo().get_param(
            'hudson_field_service.default_hourly_rate', default='0.0'
        )
        try:
            rate = float(default_rate)
        except (ValueError, TypeError):
            rate = 0.0
        for order in self:
            order.hourly_rate = rate

    @api.depends('total_products_amount', 'total_time_spent', 'hourly_rate')
    def _compute_total_amount(self):
        for order in self:
            time_cost = order.total_time_spent * order.hourly_rate
            order.total_amount = order.total_products_amount + time_cost

    @api.constrains('employee_id', 'extra_employee_ids', 'date_planned', 'duration_planned')
    def _check_planning_collision(self):
        from datetime import timedelta
        for order in self:
            if not order.date_planned or not order.duration_planned:
                continue
            
            assignee_ids = []
            if order.employee_id:
                assignee_ids.append(order.employee_id.id)
            if order.extra_employee_ids:
                assignee_ids.extend(order.extra_employee_ids.ids)
                
            if not assignee_ids:
                continue
                
            order_end = order.date_planned + timedelta(hours=order.duration_planned)
            
            domain = [
                ('id', '!=', order.id),
                ('state', 'not in', ('done', 'cancelled')),
                ('date_planned', '!=', False),
                '|', ('employee_id', 'in', assignee_ids), ('extra_employee_ids', 'in', assignee_ids),
            ]
            
            overlapping = self.search(domain)
            for other in overlapping:
                other_end = other.date_planned + timedelta(hours=other.duration_planned)
                if order.date_planned < other_end and order_end > other.date_planned:
                    other_assignee_ids = set(other.extra_employee_ids.ids)
                    if other.employee_id:
                        other_assignee_ids.add(other.employee_id.id)
                    conflict_users = set(assignee_ids) & other_assignee_ids
                    user_names = ", ".join(self.env['hr.employee'].browse(list(conflict_users)).mapped('name'))
                    raise ValidationError(_("Planning Collision! The following assignees are already booked during this time: %s") % user_names)

    # -------------------------------------------------------------------------
    # ONCHANGE METHODS
    # -------------------------------------------------------------------------

    @api.onchange('project_id')
    def _onchange_project_id(self):
        """Clear task when project changes."""
        if self.task_id and self.task_id.project_id != self.project_id:
            self.task_id = False

    @api.onchange('task_id')
    def _onchange_task_id(self):
        """
        When a task is assigned, automatically inherit the project, and — most
        importantly — detect the originating Sale Order from the project so that
        materials added to this FS order are billed to that SO.
        """
        if not self.task_id:
            return

        # Auto-fill project from task
        if self.task_id.project_id and not self.project_id:
            self.project_id = self.task_id.project_id

        if self.sale_order_id:
            return  # Already set — don't override

        project = self.task_id.project_id
        if not project:
            return

        # Method 1: Our custom sale_order_id field on project.project
        project_so = getattr(project, 'sale_order_id', False)
        if project_so:
            self.sale_order_id = project_so
            return

        # Method 2: sale_timesheet integration — task has sale_line_id
        task_line = getattr(self.task_id, 'sale_line_id', False)
        if task_line and task_line.order_id:
            self.sale_order_id = task_line.order_id
            return

    # -------------------------------------------------------------------------
    # CRUD OVERRIDES
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('field.service.order') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        # Auto-transition to scheduled when user and date are set
        result = super().write(vals)
        if 'employee_id' in vals or 'date_planned' in vals:
            for order in self:
                if order.state == 'new' and order.employee_id and order.date_planned:
                    order.state = 'scheduled'
        # Sync product lines to linked sale order whenever products change
        if 'product_line_ids' in vals:
            for order in self:
                order._sync_products_to_sale_order()
        return result

    # -------------------------------------------------------------------------
    # SALE ORDER SYNC
    # -------------------------------------------------------------------------

    def _sync_products_to_sale_order(self):
        """
        Sync field service product lines to the linked (or auto-created) sale order.

        - If the order already has a sale_order_id, add/update/remove SO lines.
        - If no SO exists AND fs_auto_sale_order is enabled, create a new SO.
        - Each product line stores a reference (sale_order_line_id) to the
          corresponding SO line so we can update it on subsequent saves.
        """
        self.ensure_one()
        IrConfig = self.env['ir.config_parameter'].sudo()

        # Respect feature flags
        billing_on = IrConfig.get_param('hudson_field_service.fs_billing', 'True') == 'True'
        auto_so = IrConfig.get_param('hudson_field_service.fs_auto_sale_order', 'True') == 'True'
        if not billing_on:
            return
        if not self.product_line_ids:
            return

        # ── Get or create the sale order ────────────────────────────────────
        sale_order = self.sale_order_id
        if not sale_order:
            if not auto_so or not self.partner_id:
                return
            sale_order = self.env['sale.order'].create({
                'partner_id': self.partner_id.id,
                'company_id': self.company_id.id,
                'origin': self.name,
                'note': _('Auto-created from Field Service Order %s') % self.name,
            })
            # Use sudo to avoid any potential write-restrict on self
            self.sudo().write({'sale_order_id': sale_order.id})

        # ── Sync each product line to a SO line ─────────────────────────────
        SaleLine = self.env['sale.order.line']
        for fs_line in self.product_line_ids:
            if fs_line.sale_order_line_id and fs_line.sale_order_line_id.exists():
                # Update existing SO line
                fs_line.sale_order_line_id.write({
                    'product_uom_qty': fs_line.quantity,
                    'price_unit': fs_line.price_unit,
                })
            else:
                # Create new SO line
                so_line = SaleLine.create({
                    'order_id': sale_order.id,
                    'product_id': fs_line.product_id.id,
                    'name': fs_line.description or fs_line.product_id.display_name,
                    'product_uom_qty': fs_line.quantity,
                    'price_unit': fs_line.price_unit,
                    'product_uom_id': (
                        fs_line.uom_id.id
                        if fs_line.uom_id
                        else fs_line.product_id.uom_id.id
                    ),
                })
                fs_line.sudo().write({'sale_order_line_id': so_line.id})

    # -------------------------------------------------------------------------
    # ACTION METHODS — TIMER
    # -------------------------------------------------------------------------
    def _format_location_message(self, event_label, latitude, longitude):
        """Format a rich chatter message with coordinates and a map button."""
        map_url = f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"
        return Markup(
            f'<div style="padding: 8px 0;">'
            f'<b>📍 {event_label}</b><br/>'
            f'<span style="color: #666;">Coordinates: {latitude:.6f}, {longitude:.6f}</span><br/>'
            f'<a href="{map_url}" target="_blank" '
            f'style="display: inline-block; margin-top: 4px; padding: 4px 12px; '
            f'background-color: #017e84; color: white; border-radius: 4px; '
            f'text-decoration: none; font-size: 13px; font-weight: bold; '
            f'box-shadow: 0 1px 3px rgba(0,0,0,0.15);">'
            f'<i class="fa fa-map-marker"></i> Open in Google Maps</a>'
            f'</div>'
        )

    def action_start_timer(self):
        """Fallback start without location (called from header button)."""
        self.ensure_one()
        if self.state not in ('new', 'scheduled'):
            raise UserError(_("You can only start a new or scheduled order."))
        if self.is_timer_running:
            raise UserError(_("Timer is already running."))
        self.write({
            'state': 'in_progress',
            'timer_start': fields.Datetime.now(),
            'date_start': fields.Datetime.now() if not self.date_start else self.date_start,
        })
        return True

    def action_start_timer_with_location(self, latitude=0.0, longitude=0.0):
        """Start timer with geolocation — called by the OWL widget."""
        self.ensure_one()
        if self.state not in ('new', 'scheduled'):
            raise UserError(_("You can only start a new or scheduled order."))
        if self.is_timer_running:
            raise UserError(_("Timer is already running."))
        now = fields.Datetime.now()
        vals = {
            'state': 'in_progress',
            'timer_start': now,
            'date_start': now if not self.date_start else self.date_start,
        }
        if latitude and longitude:
            vals['start_latitude'] = latitude
            vals['start_longitude'] = longitude
            vals['current_latitude'] = latitude
            vals['current_longitude'] = longitude
            vals['last_location_update'] = now
        self.write(vals)
        if latitude and longitude:
            self.message_post(body=self._format_location_message(
                "Timer Started", latitude, longitude
            ))
        return True

    def action_update_current_location(self, latitude=0.0, longitude=0.0):
        """
        Called periodically by the frontend to update the technician's live
        position on the map.  Only writes if the values have actually changed
        (avoids unnecessary DB writes on every poll).
        """
        self.ensure_one()
        if not latitude or not longitude:
            return True
        if (abs(self.current_latitude - latitude) > 0.00001
                or abs(self.current_longitude - longitude) > 0.00001):
            self.write({
                'current_latitude': latitude,
                'current_longitude': longitude,
                'last_location_update': fields.Datetime.now(),
            })
        return True

    def action_log_location(self, latitude=0.0, longitude=0.0, event_label="Location Logged"):
        """Called by the frontend widget to log location in chatter."""
        self.ensure_one()
        if latitude and longitude:
            self.write({
                'start_latitude': latitude,
                'start_longitude': longitude,
                'current_latitude': latitude,
                'current_longitude': longitude,
                'last_location_update': fields.Datetime.now(),
            })
            self.message_post(body=self._format_location_message(
                event_label, latitude, longitude
            ))
        return True

    def action_pause_timer(self):
        """Pause the timer — opens the stop wizard to log time."""
        self.ensure_one()
        if not self.timer_start:
            raise UserError(_('Timer is not running!'))
        return self._open_stop_wizard(action='pause')

    def action_stop_timer(self):
        """Stop the timer and complete — opens the stop wizard."""
        self.ensure_one()
        if not self.timer_start:
            raise UserError(_('Timer is not running!'))
        return self._open_stop_wizard(action='stop')

    def action_resume_timer(self):
        """Fallback resume without location."""
        self.ensure_one()
        if self.state != 'paused':
            raise UserError(_("You can only resume a paused order."))
        if self.is_timer_running:
            raise UserError(_("Timer is already running."))
        
        now = fields.Datetime.now()
        vals = {
            'state': 'in_progress',
            'timer_start': now,
        }
        if self.last_paused_time:
            elapsed_rest = (now - self.last_paused_time).total_seconds() / 3600.0
            vals['rest_time_actual'] = self.rest_time_actual + elapsed_rest
            vals['last_paused_time'] = False
            
        self.write(vals)
        return True

    def action_resume_timer_with_location(self, latitude=0.0, longitude=0.0):
        """Resume timer with geolocation — called by the OWL widget."""
        self.ensure_one()
        if self.state != 'paused':
            raise UserError(_("You can only resume a paused order."))
        if self.is_timer_running:
            raise UserError(_("Timer is already running."))
        now = fields.Datetime.now()
        vals = {
            'state': 'in_progress',
            'timer_start': now,
        }
        if self.last_paused_time:
            elapsed_rest = (now - self.last_paused_time).total_seconds() / 3600.0
            vals['rest_time_actual'] = self.rest_time_actual + elapsed_rest
            vals['last_paused_time'] = False
            
        if latitude and longitude:
            vals['current_latitude'] = latitude
            vals['current_longitude'] = longitude
            vals['last_location_update'] = now
        self.write(vals)
        if latitude and longitude:
            self.message_post(body=self._format_location_message(
                "Timer Resumed", latitude, longitude
            ))
        return True

    def _open_stop_wizard(self, action='pause'):
        """Open the stop timer wizard."""
        now = fields.Datetime.now()
        elapsed = (now - self.timer_start).total_seconds() / 3600.0 if self.timer_start else 0.0
        return {
            'name': _('Stop Timer'),
            'type': 'ir.actions.act_window',
            'res_model': 'field.service.stop.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_order_id': self.id,
                'default_duration': round(elapsed, 2),
                'default_start_time': self.timer_start,
                'default_end_time': now,
                'default_action_type': action,
            },
        }

    # -------------------------------------------------------------------------
    # ACTION METHODS — WORKFLOW
    # -------------------------------------------------------------------------

    def action_mark_done(self):
        """Mark the field service order as done."""
        self.ensure_one()
        # If timer is running, stop it first
        if self.is_timer_running:
            return self._open_stop_wizard(action='stop')

        self.write({
            'state': 'done',
            'date_end': fields.Datetime.now(),
        })

        # Move to the closing stage if one exists
        close_stage = self.env['field.service.stage'].search([('is_close', '=', True)], limit=1)
        if close_stage:
            self.stage_id = close_stage

        # Sync products to sale order on completion
        self._sync_products_to_sale_order()

        # Auto-invoice if enabled
        IrConfig = self.env['ir.config_parameter'].sudo()
        if IrConfig.get_param('hudson_field_service.auto_invoice', 'False') == 'True':
            return self.action_create_invoice()

        # Send customer satisfaction survey if enabled
        self._send_rating_survey()

    def _send_rating_survey(self):
        """
        Send the satisfaction survey to the customer if the feature is enabled
        and the order has a customer with an email address.
        """
        IrConfig = self.env['ir.config_parameter'].sudo()
        if IrConfig.get_param('hudson_field_service.fs_customer_ratings', 'False') != 'True':
            return
        if not self.partner_id or not self.partner_id.email:
            return

        # Resolve the survey to use
        survey_id_param = IrConfig.get_param('hudson_field_service.fs_rating_survey_id', False)
        survey = False
        if survey_id_param and str(survey_id_param).isdigit():
            survey = self.env['survey.survey'].browse(int(survey_id_param)).exists()
        if not survey:
            # Fall back to the default survey shipped with the module
            survey = self.env.ref(
                'hudson_field_service.field_service_satisfaction_survey',
                raise_if_not_found=False,
            )
        if not survey:
            return

        # Create a unique survey input (token) for this customer
        survey_input = survey.sudo()._create_answer(
            partner=self.partner_id,
            check_attempts=False,
        )
        self.sudo().survey_input_id = survey_input

        # Send the rating email
        template = self.env.ref(
            'hudson_field_service.mail_template_fs_rating',
            raise_if_not_found=False,
        )
        if template:
            template.sudo().send_mail(self.id, force_send=True)
            self.message_post(
                body=_("Customer Satisfaction Survey sent to %s.") % self.partner_id.email,
                message_type='notification'
            )

    def action_cancel(self):
        """Cancel the field service order."""
        self.ensure_one()
        if self.is_timer_running:
            self.write({'timer_start': False})
        self.write({'state': 'cancelled'})

    def action_reset_to_new(self):
        """Reset a cancelled/done order back to new."""
        self.ensure_one()
        self.write({
            'state': 'new',
            'date_start': False,
            'date_end': False,
            'timer_start': False,
            'is_published': False,
        })
        new_stage = self.env['field.service.stage'].search([], order='sequence, id', limit=1)
        if new_stage:
            self.stage_id = new_stage

    def action_publish_order(self):
        """Publish the order, making it visible to the technician and sending an email."""
        for order in self:
            if not order.is_published:
                order.is_published = True
                if order.employee_id and (order.employee_id.work_contact_id or order.employee_id.user_id.partner_id):
                    template = self.env.ref('hudson_field_service.mail_template_field_service_publish', raise_if_not_found=False)
                    if template:
                        template.send_mail(order.id, force_send=False)


    # -------------------------------------------------------------------------
    # ACTION METHODS — INVOICE
    # -------------------------------------------------------------------------

    def action_create_invoice(self):
        """
        Open the invoice creation flow.

        - If linked to a Sale Order: sync products first, then open the
          standard sale.advance.payment.inv wizard against that SO.
        - If standalone (no SO): fall back to our custom wizard.
        """
        self.ensure_one()
        if self.invoice_status == 'invoiced':
            raise UserError(_('This order is already invoiced!'))
        if not self.partner_id:
            raise UserError(_('Please set a customer before creating an invoice.'))

        # Route through Sale Order when available
        if self.sale_order_id:
            self._sync_products_to_sale_order()
            return {
                'name': _('Create Invoice'),
                'type': 'ir.actions.act_window',
                'res_model': 'sale.advance.payment.inv',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'active_ids': [self.sale_order_id.id],
                    'active_model': 'sale.order',
                    'active_id': self.sale_order_id.id,
                },
            }

        # Standalone: use our custom wizard
        return {
            'name': _('Create Invoice'),
            'type': 'ir.actions.act_window',
            'res_model': 'field.service.create.invoice.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_order_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_include_time': True,
                'default_include_products': True,
            },
        }

    def action_view_invoice(self):
        """Open the linked invoice."""
        self.ensure_one()
        if self.invoice_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'view_mode': 'form',
                'res_id': self.invoice_id.id,
                'target': 'current',
            }

    def action_view_sale_order(self):
        """Open the linked sale order."""
        self.ensure_one()
        if not self.sale_order_id:
            raise UserError(_('No sale order is linked to this field service order.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.sale_order_id.id,
            'target': 'current',
        }

    def action_send_report(self):
        """Open the mail compose wizard to send the report to the customer."""
        self.ensure_one()
        # Find our custom mail template
        template = self.env.ref('hudson_field_service.mail_template_field_service_report', raise_if_not_found=False)

        ctx = {
            'default_model': 'field.service.order',
            'default_res_ids': self.ids,
            'default_template_id': template.id if template else False,
            'default_use_template': bool(template),
            'default_composition_mode': 'comment',
            'mark_so_as_sent': True,
            'force_email': True,
        }
        return {
            'name': _('Send Report'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'views': [(False, 'form')],
            'view_id': False,
            'target': 'new',
            'context': ctx,
        }

    # -------------------------------------------------------------------------
    # ACTION METHODS — NAVIGATION
    # -------------------------------------------------------------------------

    def action_view_timesheets(self):
        """Open related timesheets."""
        self.ensure_one()
        return {
            'name': _('Time Entries'),
            'type': 'ir.actions.act_window',
            'res_model': 'field.service.timesheet',
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
            'context': {'default_order_id': self.id},
        }

    def action_view_project_task(self):
        """Navigate to the linked project task."""
        self.ensure_one()
        if self.task_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'project.task',
                'view_mode': 'form',
                'res_id': self.task_id.id,
                'target': 'current',
            }

    # -------------------------------------------------------------------------
    # HELPER METHODS
    # -------------------------------------------------------------------------

    def _format_duration(self, hours):
        """Format hours as HH:MM string."""
        h = int(hours)
        m = int((hours - h) * 60)
        return f'{h:02d}:{m:02d}'


class FieldServiceImage(models.Model):
    _name = 'field.service.image'
    _description = 'Field Service Image'
    _order = 'id desc'

    order_id = fields.Many2one(
        'field.service.order',
        string='Order',
        required=True,
        ondelete='cascade',
    )
    image = fields.Image(
        string='Image',
        required=True,
        max_width=1920,
        max_height=1920,
    )
    name = fields.Char(
        string='Description',
    )
    include_in_report = fields.Boolean(
        string='Include in Report',
        default=True,
        help='Whether to show this image in the printed service report and customer portal.',
    )
