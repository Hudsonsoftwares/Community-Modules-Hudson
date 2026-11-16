# -*- coding: utf-8 -*-
from datetime import datetime, date, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class DentalMaintenanceEquipment(models.Model):
    _inherit = 'maintenance.equipment'

    branch_id = fields.Many2one(
        'res.company',
        string='Clinic Branch',
        related='company_id',
        store=True,
        readonly=False,
        help='Clinic branch where this dental equipment is installed.'
    )

    equipment_condition = fields.Selection([
        ('operational', 'Operational / Good'),
        ('needs_maintenance', 'Needs Maintenance / Minor Issue'),
        ('under_repair', 'Under Repair'),
        ('out_of_order', 'Out of Order / Breakdown'),
        ('scrapped', 'Decommissioned / Scrapped')
    ], string='Equipment Condition', default='operational', tracking=True, copy=False)

    is_available = fields.Boolean(
        string='Available for Appointments',
        compute='_compute_is_available',
        store=True,
        tracking=True,
        help='Indicates whether this equipment is operational and available for clinical procedures.'
    )

    preventive_frequency_days = fields.Integer(
        string='Preventive Interval (Days)',
        default=90,
        help='Recommended preventive maintenance frequency in days as specified by manufacturer.'
    )

    last_maintenance_date = fields.Date(
        string='Last Maintenance Date',
        compute='_compute_maintenance_dates',
        store=True,
        help='Date when the latest maintenance task was completed.'
    )

    next_maintenance_date = fields.Date(
        string='Next Maintenance Date',
        compute='_compute_maintenance_dates',
        store=True,
        readonly=False,
        help='Next scheduled preventive maintenance date.'
    )

    is_overdue = fields.Boolean(
        string='Maintenance Overdue',
        compute='_compute_is_overdue',
        store=True,
        help='Flags if the scheduled maintenance date has passed without completion.'
    )

    warranty_status = fields.Selection([
        ('valid', 'Under Warranty'),
        ('expiring_soon', 'Expiring Soon (30 Days)'),
        ('expired', 'Warranty Expired'),
        ('none', 'No Warranty Specified')
    ], string='Warranty Status', compute='_compute_warranty_status', store=True)

    warranty_days_remaining = fields.Integer(
        string='Warranty Days Left',
        compute='_compute_warranty_status',
        store=True
    )

    total_maintenance_cost = fields.Float(
        string='Total Maintenance Cost',
        compute='_compute_maintenance_costs',
        store=True,
        help='Cumulative repair and spare parts expense incurred for this equipment.'
    )

    repair_request_count = fields.Integer(
        string='Repair Count',
        compute='_compute_request_counts'
    )

    preventive_request_count = fields.Integer(
        string='Preventive Count',
        compute='_compute_request_counts'
    )

    # -------------------------------------------------------------------------
    # Computes
    # -------------------------------------------------------------------------
    @api.depends('equipment_condition', 'maintenance_ids.stage_id', 'maintenance_ids.stage_id.name', 'maintenance_ids.stage_id.fold', 'maintenance_ids.equipment_availability_impact')
    def _compute_is_available(self):
        for rec in self:
            if rec.equipment_condition in ('under_repair', 'out_of_order', 'scrapped') or getattr(rec, 'scrap_date', False):
                rec.is_available = False
                continue

            # Check if any maintenance request is in a Scrap / Decommission stage
            has_scrap_req = rec.maintenance_ids.filtered(
                lambda r: r.stage_id and ('scrap' in (r.stage_id.name or '').lower() or 'decommission' in (r.stage_id.name or '').lower())
            )
            if has_scrap_req:
                rec.is_available = False
                continue

            # Check if there is any active breakdown request marking it unavailable
            active_down_reqs = rec.maintenance_ids.filtered(
                lambda r: not r.stage_id.fold and r.equipment_availability_impact in ('unavailable', 'reduced_capacity')
            )
            rec.is_available = False if active_down_reqs else True

    @api.depends('maintenance_ids.close_date', 'maintenance_ids.stage_id.fold', 'preventive_frequency_days', 'effective_date')
    def _compute_maintenance_dates(self):
        for rec in self:
            # Find latest completed maintenance request
            done_requests = rec.maintenance_ids.filtered(
                lambda r: (r.stage_id.fold or r.close_date) and (r.close_date or r.write_date)
            ).sorted(key=lambda r: r.close_date or r.write_date.date(), reverse=True)

            if done_requests:
                latest = done_requests[0]
                rec.last_maintenance_date = latest.close_date or latest.write_date.date()
            else:
                rec.last_maintenance_date = False

            # Calculate next scheduled preventive date
            freq = rec.preventive_frequency_days or 90
            base_date = rec.last_maintenance_date or rec.effective_date or fields.Date.context_today(rec)
            rec.next_maintenance_date = base_date + timedelta(days=freq)

    @api.depends('next_maintenance_date', 'equipment_condition')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.equipment_condition == 'scrapped':
                rec.is_overdue = False
            elif rec.next_maintenance_date and rec.next_maintenance_date < today:
                rec.is_overdue = True
            else:
                rec.is_overdue = False

    @api.depends('warranty_date')
    def _compute_warranty_status(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.warranty_date:
                rec.warranty_status = 'none'
                rec.warranty_days_remaining = 0
            else:
                delta = (rec.warranty_date - today).days
                rec.warranty_days_remaining = delta
                if delta < 0:
                    rec.warranty_status = 'expired'
                elif delta <= 30:
                    rec.warranty_status = 'expiring_soon'
                else:
                    rec.warranty_status = 'valid'

    @api.depends('maintenance_ids.total_cost', 'maintenance_ids.stage_id')
    def _compute_maintenance_costs(self):
        for rec in self:
            rec.total_maintenance_cost = sum(rec.maintenance_ids.mapped('total_cost'))

    def _compute_request_counts(self):
        for rec in self:
            rec.repair_request_count = len(rec.maintenance_ids.filtered(lambda r: r.maintenance_type == 'corrective'))
            rec.preventive_request_count = len(rec.maintenance_ids.filtered(lambda r: r.maintenance_type == 'preventive'))

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------
    def action_schedule_preventive_maintenance(self):
        """Quick action to generate a preventive maintenance task from the schedule."""
        self.ensure_one()
        scheduled_date = self.next_maintenance_date or fields.Date.context_today(self)
        default_team = self.maintenance_team_id.id if self.maintenance_team_id else False

        # First stage for requests
        new_stage = self.env['maintenance.stage'].search([], order='sequence asc', limit=1)

        request_vals = {
            'name': _("Preventive Service: %s") % self.name,
            'equipment_id': self.id,
            'category_id': self.category_id.id if self.category_id else False,
            'company_id': self.company_id.id if self.company_id else self.env.company.id,
            'maintenance_team_id': default_team,
            'maintenance_type': 'preventive',
            'stage_id': new_stage.id if new_stage else False,
            'schedule_date': datetime.combine(scheduled_date, datetime.min.time()),
            'equipment_availability_impact': 'reduced_capacity',
            'priority': '1',
            'description': _("<p>Routine scheduled preventive maintenance for %s per manufacturer specification interval (%d days).</p>") % (
                self.name, self.preventive_frequency_days or 90
            ),
        }
        new_req = self.env['maintenance.request'].create(request_vals)
        return {
            'name': _('Preventive Maintenance Task'),
            'type': 'ir.actions.act_window',
            'res_model': 'maintenance.request',
            'res_id': new_req.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_report_breakdown(self):
        """Quick action to report a breakdown/defect for this equipment."""
        self.ensure_one()
        return {
            'name': _('Report Breakdown / Issue'),
            'type': 'ir.actions.act_window',
            'res_model': 'maintenance.request',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_equipment_id': self.id,
                'default_category_id': self.category_id.id if self.category_id else False,
                'default_company_id': self.company_id.id if self.company_id else self.env.company.id,
                'default_maintenance_team_id': self.maintenance_team_id.id if self.maintenance_team_id else False,
                'default_maintenance_type': 'corrective',
                'default_equipment_availability_impact': 'unavailable',
                'default_priority': '2',
            }
        }

    @api.model
    def get_maintenance_dashboard_data(self, branch_id=None):
        """Fetch comprehensive, real-time maintenance dashboard metrics and lists."""
        company = self.env['res.company'].browse(branch_id) if branch_id else self.env.company
        self.env['dental.company.mixin']._dental_check_company_access(company)
        today = fields.Date.context_today(self)
        soon_threshold = today + timedelta(days=30)
        warranty_threshold = today + timedelta(days=60)

        # Base domains
        equip_domain = ['|', ('company_id', '=', False), ('company_id', '=', company.id)]
        req_domain = ['|', ('company_id', '=', False), ('company_id', '=', company.id)]

        equipments = self.search(equip_domain)
        all_requests = self.env['maintenance.request'].search(req_domain)

        # 1. KPI Counts
        total_equipment = len(equipments)
        under_maintenance = len(equipments.filtered(lambda e: not e.is_available or e.equipment_condition in ('under_repair', 'out_of_order')))
        open_repairs = len(all_requests.filtered(lambda r: not r.stage_id.fold and r.maintenance_type == 'corrective'))
        
        overdue_preventive = len(equipments.filtered(lambda e: e.is_overdue and e.equipment_condition != 'scrapped'))
        preventive_due_soon = len(equipments.filtered(
            lambda e: e.next_maintenance_date and today <= e.next_maintenance_date <= soon_threshold and not e.is_overdue
        ))
        
        warranty_expiring_soon = len(equipments.filtered(
            lambda e: e.warranty_date and today <= e.warranty_date <= warranty_threshold
        ))

        total_costs = sum(all_requests.mapped('total_cost'))

        # 2. Recent Requests (latest 10)
        recent_reqs_data = []
        for r in all_requests.sorted(key=lambda req: req.create_date or datetime.min, reverse=True)[:10]:
            recent_reqs_data.append({
                'id': r.id,
                'name': r.name,
                'equipment_id': r.equipment_id.id if r.equipment_id else False,
                'equipment_name': r.equipment_id.name if r.equipment_id else 'General Equipment',
                'category_name': r.category_id.name if r.category_id else 'Uncategorized',
                'priority': r.priority or '1',
                'maintenance_type': r.maintenance_type or 'corrective',
                'stage_id': r.stage_id.id if r.stage_id else False,
                'stage_name': r.stage_id.name if r.stage_id else 'New',
                'stage_done': bool(r.stage_id.fold) if r.stage_id else False,
                'schedule_date': fields.Datetime.to_string(r.schedule_date) if r.schedule_date else '',
                'total_cost': r.total_cost or 0.0,
                'impact': r.equipment_availability_impact or 'unavailable',
            })

        # 3. Upcoming Preventive Schedules (sorted by next date)
        upcoming_preventive_data = []
        preventive_candidates = equipments.filtered(lambda e: e.next_maintenance_date and e.equipment_condition != 'scrapped').sorted(key=lambda e: e.next_maintenance_date)
        for eq in preventive_candidates[:8]:
            upcoming_preventive_data.append({
                'id': eq.id,
                'name': eq.name,
                'serial_no': eq.serial_no or '',
                'category_name': eq.category_id.name if eq.category_id else 'Uncategorized',
                'next_date': fields.Date.to_string(eq.next_maintenance_date),
                'frequency_days': eq.preventive_frequency_days or 90,
                'is_overdue': eq.is_overdue,
                'technician_name': eq.technician_user_id.name if eq.technician_user_id else 'Unassigned',
                'condition': eq.equipment_condition,
            })

        # 4. Equipment by Category
        category_counts = {}
        for eq in equipments:
            cat_name = eq.category_id.name if eq.category_id else 'Other Equipment'
            category_counts[cat_name] = category_counts.get(cat_name, 0) + 1

        # 5. Equipment Condition Breakdown
        condition_counts = {
            'operational': 0,
            'needs_maintenance': 0,
            'under_repair': 0,
            'out_of_order': 0,
            'scrapped': 0
        }
        for eq in equipments:
            cond = eq.equipment_condition or 'operational'
            if cond in condition_counts:
                condition_counts[cond] += 1
            else:
                condition_counts['operational'] += 1

        # 6. Top High Maintenance Cost / Breakdown Equipments
        costly_equipments = []
        for eq in equipments.filtered(lambda e: e.total_maintenance_cost > 0 or e.repair_request_count > 0).sorted(key=lambda e: e.total_maintenance_cost, reverse=True)[:6]:
            costly_equipments.append({
                'id': eq.id,
                'name': eq.name,
                'category': eq.category_id.name if eq.category_id else 'Equipment',
                'repair_count': eq.repair_request_count,
                'total_cost': eq.total_maintenance_cost,
                'condition': eq.equipment_condition,
            })

        # 7. Multi-Branch list
        branches = [{'id': c.id, 'name': c.name} for c in self.env['res.company'].search([])]

        return {
            'current_branch_id': company.id,
            'current_branch_name': company.name or 'Main Clinic',
            'branches': branches,
            'kpis': {
                'total_equipment': total_equipment,
                'under_maintenance': under_maintenance,
                'open_repairs': open_repairs,
                'overdue_preventive': overdue_preventive,
                'preventive_due_soon': preventive_due_soon,
                'warranty_expiring_soon': warranty_expiring_soon,
                'total_maintenance_cost': round(total_costs, 2),
            },
            'recent_requests': recent_reqs_data,
            'upcoming_preventive': upcoming_preventive_data,
            'category_counts': category_counts,
            'condition_counts': condition_counts,
            'costly_equipments': costly_equipments,
        }


class DentalMaintenanceRequest(models.Model):
    _inherit = 'maintenance.request'

    branch_id = fields.Many2one(
        'res.company',
        string='Clinic Branch',
        related='company_id',
        store=True,
        readonly=False
    )

    request_date = fields.Date(
        string='Request Date',
        default=fields.Date.context_today,
        required=True
    )

    equipment_availability_impact = fields.Selection([
        ('none', 'No Impact (Equipment Fully Usable)'),
        ('reduced_capacity', 'Reduced Capacity (Minor Limitations)'),
        ('unavailable', 'Unavailable (Out of Service)')
    ], string='Availability Impact', default='unavailable', required=True, tracking=True,
       help='Defines how this equipment defect affects patient appointments and clinical procedures.')

    resolution_notes = fields.Html(
        string='Resolution & Technical Notes',
        help='Technical diagnosis, actions performed, root causes, and verification remarks.'
    )

    repair_cost = fields.Float(
        string='Service / Labor Cost',
        default=0.0,
        tracking=True,
        help='Cost of technician labor or external service provider charges.'
    )

    parts_cost = fields.Float(
        string='Parts & Consumables Cost',
        compute='_compute_parts_cost',
        store=True,
        help='Total cost of replacement spare parts used during repair.'
    )

    total_cost = fields.Float(
        string='Total Maintenance Cost',
        compute='_compute_total_cost',
        store=True,
        help='Sum of labor/service and spare parts expenses.'
    )

    parts_used_ids = fields.One2many(
        'maintenance.request.parts.line',
        'request_id',
        string='Spare Parts Used'
    )

    # -------------------------------------------------------------------------
    # Computes
    # -------------------------------------------------------------------------
    @api.depends('parts_used_ids.subtotal')
    def _compute_parts_cost(self):
        for rec in self:
            rec.parts_cost = sum(rec.parts_used_ids.mapped('subtotal'))

    @api.depends('repair_cost', 'parts_cost')
    def _compute_total_cost(self):
        for rec in self:
            rec.total_cost = (rec.repair_cost or 0.0) + (rec.parts_cost or 0.0)

    # -------------------------------------------------------------------------
    # Stage & Lifecycle Handlers
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        requests = super().create(vals_list)
        for req in requests:
            req._sync_equipment_condition()
        return requests

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('stage_id', 'equipment_availability_impact', 'equipment_id')):
            self._sync_equipment_condition()
        return res

    def _sync_equipment_condition(self):
        """Update equipment condition and availability based on active maintenance requests."""
        for req in self:
            if not req.equipment_id:
                continue
            equipment = req.equipment_id
            stage_name = (req.stage_id.name or '').strip().lower() if req.stage_id else ''

            # 1. SCRAP STAGE (Highest priority): equipment is condemned and scrapped
            if 'scrap' in stage_name or 'decommission' in stage_name:
                vals = {
                    'equipment_condition': 'scrapped',
                    'is_available': False,
                }
                if hasattr(equipment, 'scrap_date') and not equipment.scrap_date:
                    vals['scrap_date'] = fields.Date.context_today(req)
                equipment.write(vals)
                continue

            # If equipment is already scrapped, do not let repair/closure of other tickets restore it
            if equipment.equipment_condition == 'scrapped' or getattr(equipment, 'scrap_date', False):
                continue

            # 2. Completed / Repaired / Closed stage (Folded, but NOT Scrap)
            if req.stage_id and req.stage_id.fold:
                # Check if there is any other request in Scrap stage
                has_scrap_req = self.search([
                    ('equipment_id', '=', equipment.id),
                    ('stage_id.name', 'ilike', 'scrap')
                ], limit=1)
                if has_scrap_req:
                    equipment.write({
                        'equipment_condition': 'scrapped',
                        'is_available': False,
                    })
                    continue

                # Check if there are other open breakdown requests
                other_open = self.search([
                    ('equipment_id', '=', equipment.id),
                    ('id', '!=', req.id),
                    ('stage_id.fold', '=', False),
                    ('equipment_availability_impact', 'in', ('unavailable', 'reduced_capacity'))
                ])
                if not other_open and equipment.equipment_condition in ('under_repair', 'out_of_order', 'needs_maintenance'):
                    equipment.write({
                        'equipment_condition': 'operational',
                        'is_available': True,
                    })
            else:
                # 3. Active open request (New, Assigned, In Progress, etc.)
                if req.equipment_availability_impact == 'unavailable':
                    new_cond = 'out_of_order' if req.maintenance_type == 'corrective' else 'under_repair'
                    equipment.write({
                        'equipment_condition': new_cond,
                        'is_available': False,
                    })
                elif req.equipment_availability_impact == 'reduced_capacity':
                    equipment.write({
                        'equipment_condition': 'needs_maintenance',
                    })

    def action_mark_repaired(self):
        """Mark request as repaired and restore equipment availability."""
        for rec in self:
            repaired_stage = self.env['maintenance.stage'].search([
                '|', ('name', 'ilike', 'Repaired'), ('name', 'ilike', 'Done')
            ], limit=1)
            if not repaired_stage:
                repaired_stage = self.env['maintenance.stage'].search([('fold', '=', True)], limit=1)
            if repaired_stage:
                rec.stage_id = repaired_stage.id
            rec.close_date = fields.Date.context_today(rec)
            rec._sync_equipment_condition()
        return True

    def action_mark_closed(self):
        """Close maintenance request."""
        for rec in self:
            closed_stage = self.env['maintenance.stage'].search([
                ('name', 'ilike', 'Closed')
            ], limit=1)
            if not closed_stage:
                closed_stage = self.env['maintenance.stage'].search([('fold', '=', True)], limit=1)
            if closed_stage:
                rec.stage_id = closed_stage.id
            if not rec.close_date:
                rec.close_date = fields.Date.context_today(rec)
            rec._sync_equipment_condition()
        return True


class DentalMaintenancePartsLine(models.Model):
    _name = 'maintenance.request.parts.line'
    _description = 'Maintenance Request Spare Parts Line'
    _order = 'id desc'

    request_id = fields.Many2one(
        'maintenance.request',
        string='Maintenance Request',
        required=True,
        ondelete='cascade'
    )
    product_id = fields.Many2one(
        'product.product',
        string='Spare Part / Product',
        domain="[('type', '!=', 'service')]",
        help='Optional link to inventory product catalog for parts tracking.'
    )
    name = fields.Char(
        string='Part Description',
        required=True,
        help='Name or reference of the spare part, component, or consumable used.'
    )
    quantity = fields.Float(
        string='Quantity',
        default=1.0,
        required=True
    )
    unit_cost = fields.Float(
        string='Unit Cost',
        default=0.0
    )
    subtotal = fields.Float(
        string='Subtotal',
        compute='_compute_subtotal',
        store=True
    )

    @api.depends('quantity', 'unit_cost')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = (line.quantity or 0.0) * (line.unit_cost or 0.0)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.display_name
            self.unit_cost = self.product_id.standard_price or 0.0
