# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytz

from odoo import api, fields, models, _
from odoo.fields import Domain
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import format_date
from odoo.tools.intervals import Intervals


class FsPlanningSlot(models.Model):
    _name = 'fs.planning.slot'
    _description = 'Field Service Planning Slot'
    _order = 'date_start asc, resource_id asc'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    # Employee, project, sales order, template... of the shift's company
    _check_company_auto = True

    # Dates are required, except on the shifts of a sales order still to plan.
    _dates_set_or_to_plan = models.Constraint(
        'CHECK((date_start IS NOT NULL AND date_end IS NOT NULL) OR sale_line_id IS NOT NULL)',
        "Set the start and end dates of the shift.",
    )

    name = fields.Char(string='Description')
    active = fields.Boolean(default=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
    ], string='Status', default='draft', required=True, tracking=True)
    
    resource_id = fields.Many2one(
        'hr.employee',
        string='Resource',
        ondelete='cascade',
        index=True,
        check_company=True,
    )
    role_id = fields.Many2one(
        'fs.planning.role',
        string='Role',
        ondelete='restrict',
        index=True,
    )
    color = fields.Integer(
        related='role_id.color',
        string='Color',
        readonly=True,
    )
    # Required, except on the shifts of a sales order still to plan (see
    # sale.order.line._planning_slot_generation and _check_dates_set).
    date_start = fields.Datetime(
        string='Start Date',
        index=True,
    )
    date_end = fields.Datetime(
        string='End Date',
        index=True,
    )
    allocated_hours = fields.Float(
        string='Allocated Time',
        compute='_compute_allocated_hours',
        store=True,
        readonly=False,
        help='Working time of the shift: its duration minus the break. '
             'On a shift to plan, the hours left to schedule.',
    )
    break_hours = fields.Float(
        string='Break',
        default=0.0,
    )
    shift_status = fields.Selection(
        [
            ('draft', 'Draft'),
            ('scheduled', 'Scheduled'),
        ],
        string='Shift Status',
        compute='_compute_shift_status',
        help='Draft: not published yet. Scheduled: published to the resource.',
    )
    
    project_id = fields.Many2one(
        'project.project',
        string='Project',
        ondelete='set null',
        check_company=True,
    )
    task_id = fields.Many2one(
        'project.task',
        string='Task',
        domain="[('project_id', '=?', project_id)]",
        ondelete='set null',
        check_company=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        ondelete='set null',
        check_company=True,
    )
    sale_line_id = fields.Many2one(
        'sale.order.line',
        string='Sales Order Item',
        ondelete='set null',
        index='btree_not_null',
        copy=False,
        check_company=True,
        help='Service sold whose hours are planned by this shift (Plan Services on the product).',
    )
    is_to_plan = fields.Boolean(
        string='To Plan',
        compute='_compute_is_to_plan',
        search='_search_is_to_plan',
        help='Shift of a sales order whose dates are not scheduled yet.',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        ondelete='set null',
        check_company=True,
    )

    shift_template_id = fields.Many2one(
        'fs.shift.template',
        string='Template',
        ondelete='set null',
        check_company=True,
    )
    available_template_ids = fields.Many2many(
        'fs.shift.template',
        compute='_compute_available_template_ids',
        help='Templates offered on the shift: those of the roles of its resource, '
             'and the templates without role (offered to everyone).',
    )
    request_to_switch = fields.Boolean(
        string='Replacement Requested',
        copy=False,
        tracking=True,
        help='The resource asked to be replaced on this shift: other employees can take it.',
    )
    is_planning_manager = fields.Boolean(compute='_compute_is_planning_manager')
    is_own_shift = fields.Boolean(compute='_compute_shift_changes')
    can_request_switch = fields.Boolean(compute='_compute_shift_changes')
    can_self_unassign = fields.Boolean(compute='_compute_shift_changes')
    can_take_shift = fields.Boolean(compute='_compute_shift_changes')
    template_creation = fields.Boolean(
        string='Save as Template',
        copy=False,
        help='Create a shift template with the hours, role and project of this shift.',
    )
    note = fields.Text(string='Note')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        compute='_compute_company_id',
        store=True,
        readonly=False,
        precompute=True,
        required=True,
        help="The company of the shift's employee.",
    )

    @api.depends('resource_id')
    def _compute_company_id(self):
        for slot in self:
            slot.company_id = slot.resource_id.company_id or slot.company_id or self.env.company

    @api.depends('resource_id', 'company_id')
    def _compute_available_template_ids(self):
        templates = self.env['fs.shift.template'].search([])
        for slot in self:
            slot.available_template_ids = templates.filtered(
                lambda t: (not t.company_id or t.company_id == slot.company_id)
                and (not t.role_id or not slot.resource_id or slot.resource_id in t.role_id.resource_ids)
            )

    @api.depends('date_start', 'date_end', 'break_hours')
    def _compute_allocated_hours(self):
        for slot in self:
            if slot.date_start and slot.date_end:
                delta = slot.date_end - slot.date_start
                slot.allocated_hours = max(delta.total_seconds() / 3600.0 - slot.break_hours, 0.0)
            elif not slot.sale_line_id:
                slot.allocated_hours = 0.0
            # else: a shift to plan keeps the hours left to schedule

    @api.depends('date_start', 'sale_line_id')
    def _compute_is_to_plan(self):
        for slot in self:
            slot.is_to_plan = bool(slot.sale_line_id) and not slot.date_start

    def _search_is_to_plan(self, operator, value):
        if operator in ('=', '!='):
            positive = bool(value) == (operator == '=')
        elif operator in ('in', 'not in'):
            positive = (True in value) == (operator == 'in')
        else:
            return NotImplemented
        to_plan = Domain('sale_line_id', '!=', False) & Domain('date_start', '=', False)
        return to_plan if positive else ~to_plan

    @api.depends('state')
    def _compute_shift_status(self):
        for slot in self:
            slot.shift_status = 'scheduled' if slot.state == 'published' else 'draft'

    @api.depends('resource_id', 'state', 'request_to_switch', 'date_end')
    @api.depends_context('uid')
    @api.depends_context('uid')
    def _compute_is_planning_manager(self):
        self.is_planning_manager = self.env.user.has_group('hudson_planning.group_planning_manager')

    def _compute_shift_changes(self):
        mode = self._get_shift_change_mode()
        now = fields.Datetime.now()
        for slot in self:
            own = bool(slot.resource_id.user_id) and slot.resource_id.user_id == self.env.user
            usable = slot.state == 'published' and bool(slot.id) and (not slot.date_end or slot.date_end > now)
            slot.is_own_shift = own
            slot.can_request_switch = usable and own and mode == 'switch' and not slot.request_to_switch
            slot.can_self_unassign = usable and own and mode == 'unassign'
            slot.can_take_shift = usable and slot.request_to_switch and not own and bool(self.env.user.employee_id)

    @api.model
    def _get_shift_change_mode(self):
        return self.env['ir.config_parameter'].sudo().get_str('hudson_planning.employee_unavailabilities', 'switch')

    @api.constrains('break_hours', 'date_start', 'date_end')
    def _check_break_hours(self):
        for slot in self:
            if slot.break_hours < 0:
                raise ValidationError(_('The break cannot be negative.'))
            if slot.date_start and slot.date_end and slot.break_hours * 3600 > (slot.date_end - slot.date_start).total_seconds():
                raise ValidationError(_('The break cannot be longer than the shift.'))

    @api.constrains('date_start', 'date_end', 'sale_line_id')
    def _check_dates(self):
        for slot in self:
            if not (slot.date_start and slot.date_end) and not (slot.sale_line_id and not slot.date_start and not slot.date_end):
                raise ValidationError(_('Set the start and end dates of the shift.'))
            if slot.date_start and slot.date_end and slot.date_start > slot.date_end:
                raise ValidationError(_('Start date must be before end date.'))

    @api.constrains('date_start', 'date_end', 'resource_id')
    def _check_overlap(self):
        if self.env.context.get('force_generate'):
            return
        for slot in self:
            if not slot.resource_id or not slot.date_start or not slot.date_end:
                continue
            domain = [
                ('resource_id', '=', slot.resource_id.id),
                ('id', '!=', slot.id),
                ('date_start', '<', slot.date_end),
                ('date_end', '>', slot.date_start),
            ]
            # sudo: a conflict must be detected even when the other slot is
            # hidden from the current user by record rules.
            overlapping = self.env['fs.planning.slot'].sudo().search(domain).filtered(slot._conflicts_with)[:1]
            if overlapping:
                raise ValidationError(slot._get_overlap_message(overlapping))

    def _conflicts_with(self, other):
        """Whether ``other`` (an overlapping slot of the same resource) blocks ``self``.

        Hook for modules that add slot types which may legitimately overlap.
        """
        return True

    def _get_overlap_message(self, other):
        return _("Overlap Alert: The employee '%s' is already assigned to a shift from %s to %s that conflicts with this assignment. \n\n(Note: If you assign via the Shift Generation wizard, you will have an option to 'Proceed Anyway' and override this restriction).") % (
            self.resource_id.name,
            other.date_start.strftime('%Y-%m-%d %H:%M'),
            other.date_end.strftime('%Y-%m-%d %H:%M')
        )

    # -------------------------------------------------------------------------
    # MAP VIEW
    # -------------------------------------------------------------------------

    # Customers geolocated per map load (each lookup calls the geocoding service)
    _MAP_GEOLOCATE_LIMIT = 20

    @api.model
    def get_map_view_data(self, domain, group_by, offset=0, limit=80):
        """Data of the map view (``fs_map``): the shifts of the page, located at
        their customer, and grouped like the side panel.

        :param group_by: group bys of the search view; the side panel groups
            by the first one (by resource if none)
        """
        domain = Domain(domain or [])
        slots = self.search(domain, offset=offset, limit=limit, order='date_start, id')
        total = self.search_count(domain)
        group_field = (group_by[0] if group_by else 'resource_id').split(':')[0]
        if group_field not in self._fields:
            group_field = 'resource_id'
        field = self._fields[group_field]

        # sudo: the address of the customers of the shifts the user may see
        partners = slots.partner_id.sudo()
        self._map_geolocate(partners.filtered(lambda p: not (p.partner_latitude or p.partner_longitude)))

        groups = {}
        records = []
        for slot in slots:
            key, label = self._map_group_of(slot, field)
            groups.setdefault(key, {'key': key, 'name': label})
            partner = slot.partner_id.sudo()
            located = bool(partner and (partner.partner_latitude or partner.partner_longitude))
            records.append({
                'id': slot.id,
                'name': slot._get_schedule_slot_values()['label'] or slot.display_name,
                'partner_name': partner.display_name or '',
                'address': partner._display_address(without_name=True).replace('\n', ', ').strip(', ') if partner else '',
                'latitude': partner.partner_latitude if located else False,
                'longitude': partner.partner_longitude if located else False,
                'date_start': fields.Datetime.to_string(slot.date_start),
                'date_end': fields.Datetime.to_string(slot.date_end),
                'state': slot.state,
                'group_key': key,
            })
        ordered = sorted(groups.values(), key=lambda g: (g['key'] is False, (g['name'] or '').lower()))
        return {
            'records': records,
            'groups': ordered,
            'group_field': group_field,
            'group_field_string': field.string,
            'total': total,
        }

    @api.model
    def _map_group_of(self, slot, field):
        value = slot[field.name]
        if field.type == 'many2one':
            if not value:
                return False, _("Open Shifts") if field.name == 'resource_id' else _("None")
            return value.id, value.display_name
        if field.type == 'selection':
            return value, dict(field._description_selection(self.env)).get(value, value)
        if field.type in ('date', 'datetime'):
            day = fields.Date.to_string(fields.Datetime.context_timestamp(slot, value).date() if field.type == 'datetime' and value else value)
            return day or False, day or _("None")
        return value or False, str(value) if value else _("None")

    @api.model
    def _map_geolocate(self, partners):
        """Locate customers without coordinates (base_geolocalize), a few per load."""
        if not partners or not hasattr(partners, 'geo_localize'):
            return
        for partner in partners[:self._MAP_GEOLOCATE_LIMIT]:
            if not (partner.street or partner.city or partner.zip):
                continue
            try:
                with self.env.cr.savepoint():
                    partner.geo_localize()
            except Exception:  # noqa: BLE001 - an unreachable geocoder must not break the map
                continue

    # -------------------------------------------------------------------------
    # SCHEDULE VIEW
    # -------------------------------------------------------------------------

    @api.model
    def get_schedule_data(self, date_from, date_to):
        """Data for the planning schedule client action."""
        slots = self.search([
            ('date_start', '>=', date_from),
            ('date_start', '<', date_to),
        ])
        return {
            'slots': slots.read(self._get_schedule_fields()),
        }

    @api.model
    def _get_schedule_fields(self):
        return ['id', 'name', 'resource_id', 'role_id', 'sale_order_id', 'date_start', 'date_end', 'state', 'partner_id', 'allocated_hours', 'request_to_switch']

    @api.model
    def get_schedule_view_data(self, domain, group_by, date_from, date_to):
        """Data of the schedule view (``fs_schedule``) for a period.

        :param domain: domain of the search view
        :param group_by: group bys of the search view; the rows are the groups
            of the first one (no group by: a single row)
        :param date_from, date_to: UTC bounds of the period
        """
        period = Domain('date_start', '<', date_to) & Domain('date_end', '>', date_from)
        full_domain = Domain(domain or []) & period
        slots = self.search(full_domain)
        group_field = group_by[0] if group_by else False
        start = fields.Datetime.to_datetime(date_from)
        end = fields.Datetime.to_datetime(date_to)

        rows = {}
        row_of_slot = {}
        if group_field:
            fname = group_field.split(':')[0]
            field = self._fields[fname]
            for group in self.formatted_read_group(full_domain, [group_field], ['id:array_agg']):
                key, label = self._schedule_row_key(field, group[group_field])
                rows[key] = {'key': key, 'name': label}
                for slot_id in group['id:array_agg']:
                    row_of_slot[slot_id] = key
            if not domain and fname in ('resource_id', 'role_id'):
                # No filter: every resource (role) is shown, even without shifts.
                for key, label in self._schedule_all_rows(fname):
                    rows.setdefault(key, {'key': key, 'name': label})
            if fname in ('resource_id', 'role_id'):
                rows.setdefault(False, {'key': False, 'name': self._schedule_row_key(field, False)[1]})
        else:
            rows[False] = {'key': False, 'name': _("Shifts")}
            row_of_slot = dict.fromkeys(slots.ids, False)

        planned = dict.fromkeys(rows, 0.0)
        slot_values = []
        for slot, values in zip(slots, slots.read(self._get_schedule_fields())):
            key = row_of_slot.get(slot.id, False)
            values.update(slot._get_schedule_slot_values())
            values['row_key'] = key
            slot_values.append(values)
            duration = (slot.date_end - slot.date_start).total_seconds()
            overlap = (min(slot.date_end, end) - max(slot.date_start, start)).total_seconds()
            if duration > 0:
                planned[key] = planned.get(key, 0.0) + slot.allocated_hours * max(overlap, 0) / duration

        if group_field and group_field.split(':')[0] == 'resource_id':
            self._add_schedule_resource_info(rows, start, end)
        ordered = sorted(rows.values(), key=lambda r: (r['key'] is not False, (r['name'] or '').lower()))
        for row in ordered:
            row['planned_hours'] = planned.get(row['key'], 0.0)
        return {
            'rows': ordered,
            'slots': slot_values,
            'to_plan': self._get_schedule_to_plan(date_from, date_to),
            'group_field': group_field,
        }

    @api.model
    def _schedule_row_key(self, field, value):
        """(key, label) of a row from a formatted_read_group value."""
        if isinstance(value, (list, tuple)):
            return value[0], value[1]
        if value is False or value is None:
            if field.name == 'resource_id':
                return False, _("Open Shifts")
            return False, _("None")
        if field.type == 'selection':
            return value, dict(field._description_selection(self.env)).get(value, value)
        return value, str(value)

    @api.model
    def _schedule_all_rows(self, fname):
        if fname == 'resource_id':
            if not self.env.user.has_group('hudson_planning.group_planning_manager'):
                # Employees only see their own planning
                return [(e.id, e.name) for e in self.env.user.employee_ids]
            employees = self.env['hr.employee'].search([('company_id', 'in', self.env.companies.ids + [False])])
            return [(e.id, e.name) for e in employees]
        return [(r.id, r.name) for r in self.env['fs.planning.role'].search([])]

    @api.model
    def _add_schedule_resource_info(self, rows, start, end):
        """Avatar, job, capacity and days off of the resources of the period."""
        employees = self.env['hr.employee'].browse([k for k in rows if k]).exists()
        utc_start = pytz.utc.localize(start)
        utc_end = pytz.utc.localize(end)
        work_data = employees._get_work_days_data_batch(utc_start, utc_end, compute_leaves=True)
        for employee in employees:
            row = rows[employee.id]
            calendar = employee.resource_calendar_id
            work_days = set(calendar.attendance_ids.mapped('dayofweek')) if calendar else {'0', '1', '2', '3', '4'}
            tz = pytz.timezone(employee.tz or self.env.user.tz or 'UTC')
            days_off = []
            day = utc_start.astimezone(tz).date()
            while day < utc_end.astimezone(tz).date():
                if str(day.weekday()) not in work_days:
                    days_off.append(fields.Date.to_string(day))
                day += timedelta(days=1)
            if calendar:
                for leave_start, leave_end, _leave in calendar._leave_intervals_batch(
                        utc_start, utc_end, resources_per_tz={tz: employee.resource_id})[employee.resource_id.id]:
                    day = leave_start.astimezone(tz).date()
                    while day <= leave_end.astimezone(tz).date():
                        days_off.append(fields.Date.to_string(day))
                        day += timedelta(days=1)
            row.update({
                'avatar': f'/web/image/hr.employee.public/{employee.id}/avatar_128',
                'job_title': employee.job_title or '',
                'capacity_hours': work_data.get(employee.id, {}).get('hours', 0.0),
                'days_off': sorted(set(days_off)),
            })

    def _get_schedule_slot_values(self):
        """Extra values of a shift in the schedule view (label, color...)."""
        self.ensure_one()
        return {
            'label': self.name or self.partner_id.display_name or self.role_id.display_name or '',
            'color': self.role_id.color or 0,
            'is_job': False,
        }

    @api.model
    def _get_schedule_to_plan(self, date_from, date_to):
        """Side panel of the schedule: work still to be planned, dragged onto
        the schedule to plan it (see ``action_plan_from_schedule``).

        Base: the shifts of the confirmed sales orders not scheduled yet
        (Plan Services on the product).

        :return: list of ``{'ref': 'model,id', 'name', 'hours'}``
        """
        slots = self.search([('is_to_plan', '=', True), ('company_id', 'in', self.env.companies.ids)],
                            order='sale_order_id, id')
        return [{
            'ref': f'fs.planning.slot,{slot.id}',
            'name': slot._get_to_plan_label(),
            'hours': slot.allocated_hours,
        } for slot in slots]

    def _get_to_plan_label(self):
        self.ensure_one()
        # sudo: planners without sales rights plan the orders too.
        order = self.sudo().sale_order_id
        hours = self.allocated_hours
        minutes = round(hours * 60)
        duration = '%d:%02d' % divmod(minutes, 60) if minutes % 60 else '%d' % (minutes // 60)
        return _(
            "%(order)s - %(name)s (%(role)s, %(hours)sh)",
            order=' - '.join(filter(None, [order.name, order.partner_id.display_name])),
            name=self.name or self.sudo().sale_line_id.product_id.display_name,
            role=self.role_id.display_name or _("no role"),
            hours=duration,
        )

    @api.model
    def action_plan_from_schedule(self, ref, group_field, row_key, date_start, date_end):
        """Plan a shift of a sales order dropped on the schedule: its hours
        are scheduled in the working time of the day it was dropped on (from
        the dropped time), for the resource of the row; what does not fit stays
        to plan."""
        model, _sep, res_id = ref.partition(',')
        if model != 'fs.planning.slot':
            raise UserError(_("This cannot be planned from the schedule."))
        self._check_planning_manager()
        slot = self.browse(int(res_id)).exists()
        if not slot or not slot.is_to_plan:
            raise UserError(_("This shift has already been planned."))
        employee = self.env['hr.employee']
        extra_vals = {}
        if group_field == 'resource_id' and row_key:
            employee = employee.browse(row_key)
        elif group_field in ('role_id', 'project_id', 'task_id') and row_key:
            extra_vals[group_field] = row_key
        start = fields.Datetime.to_datetime(date_start)
        tz = ZoneInfo(employee.tz or self.env.user.tz or 'UTC')
        local_start = start.replace(tzinfo=UTC).astimezone(tz)
        day_end = datetime.combine(local_start.date() + timedelta(days=1), time.min, tzinfo=tz)
        planned = slot._plan_hours(employee, start, day_end.astimezone(UTC).replace(tzinfo=None), extra_vals=extra_vals)
        if not planned:
            raise UserError(_(
                "%(who)s has no working time left on %(day)s to plan this shift.",
                who=employee.name or _("The company"),
                day=format_date(self.env, local_start.date()),
            ))
        return True

    # -------------------------------------------------------------------------
    # SALES ORDERS: shifts to plan
    # -------------------------------------------------------------------------

    def _blocks_sale_planning(self, other):
        """Whether the shift ``other`` makes its resource unavailable to plan
        the hours of ``self`` (a shift to plan)."""
        return True

    def _get_free_work_blocks(self, employee, date_from, date_to):
        """Free working time of ``employee`` (open shift: of the company)
        between two naive UTC datetimes: its working schedule minus its time
        off and its shifts.

        :return: list of blocks, one per day and run of free time, each a list
            of naive UTC ``(start, end)`` (several intervals: e.g. around lunch)
        """
        self.ensure_one()
        utc = UTC
        start, end = date_from.replace(tzinfo=utc), date_to.replace(tzinfo=utc)
        if employee:
            calendar = employee.resource_calendar_id or employee.company_id.resource_calendar_id
            if not calendar:
                return []
            tz = ZoneInfo(employee.tz or self.env.user.tz or 'UTC')
            work = calendar._work_intervals_batch(start, end, resources_per_tz={tz: employee.resource_id})[employee.resource_id.id]
            # sudo: shifts hidden by the record rules still make the resource busy.
            others = self.sudo().search([
                ('resource_id', '=', employee.id), ('id', '!=', self.id),
                ('date_start', '<', date_to), ('date_end', '>', date_from),
            ]).filtered(self._blocks_sale_planning)
            busy = [(o.date_start.replace(tzinfo=utc), o.date_end.replace(tzinfo=utc)) for o in others]
            work = work - Intervals([(b, e, self.env['fs.planning.slot']) for b, e in busy])
        else:
            calendar = self.company_id.resource_calendar_id or self.env.company.resource_calendar_id
            if not calendar:
                return []
            tz = ZoneInfo(self.env.user.tz or 'UTC')
            work = calendar._work_intervals_batch(start, end, resources_per_tz={tz: self.env['resource.resource']})[False]
            busy = []

        blocks = []
        last_day = last_end = None
        for begin, stop, _records in work:
            begin, stop = begin.astimezone(utc), stop.astimezone(utc)
            day = begin.astimezone(tz).date()
            # Same day and no shift in between (e.g. lunch): one shift with a break.
            if blocks and day == last_day and not any(b < begin and e > last_end for b, e in busy):
                blocks[-1].append((begin, stop))
            else:
                blocks.append([(begin, stop)])
            last_day, last_end = day, stop
        return [[(b.replace(tzinfo=None), e.replace(tzinfo=None)) for b, e in block] for block in blocks]

    def _prepare_planned_shift_values(self, employee, date_start, date_end, break_hours):
        """Values of a shift planning (part of) the hours of a shift to plan."""
        self.ensure_one()
        return {
            'name': self.name,
            'sale_line_id': self.sale_line_id.id,
            'sale_order_id': self.sale_order_id.id,
            'role_id': self.role_id.id,
            'project_id': self.project_id.id,
            'task_id': self.task_id.id,
            'note': self.note,
            'company_id': self.company_id.id,
            'resource_id': employee.id,
            'date_start': date_start,
            'date_end': date_end,
            'break_hours': break_hours,
            'state': 'draft',
        }

    def _plan_hours(self, employee, date_from, date_to, extra_vals=None):
        """Schedule the hours of this shift to plan in the free working time of
        ``employee`` (none: an open shift, in the company's working hours)
        between two naive UTC datetimes: one shift per day. The hours that do
        not fit stay to plan (this shift, deleted once all is planned).

        :return: the created shifts
        """
        self.ensure_one()
        remaining = self.allocated_hours
        vals_list = []
        for block in self._get_free_work_blocks(employee, date_from, date_to):
            if remaining < 1 / 60:
                break
            worked = 0.0
            end = block[0][0]
            for begin, stop in block:
                take = min((stop - begin).total_seconds() / 3600, remaining - worked)
                take = round(take * 60) / 60  # whole minutes
                if take <= 0:
                    break
                end = begin + timedelta(hours=take)
                worked += take
            if worked < 1 / 60:
                continue
            breaks = max(round((end - block[0][0]).total_seconds() / 3600 - worked, 4), 0.0)
            vals = self._prepare_planned_shift_values(employee, block[0][0], end, breaks)
            vals.update(extra_vals or {})
            vals_list.append(vals)
            remaining -= worked
        if not vals_list:
            return self.browse()
        # Creating them updates (or deletes) this shift to plan.
        return self.create(vals_list)

    def _update_sale_hours_to_plan(self, lines=None):
        """Hours to plan of the sales order lines follow their planned shifts."""
        if self.env.context.get('planning_slot_generation'):
            return
        lines = ((lines or self.env['sale.order.line']) | self.sale_line_id).exists()
        if lines:
            lines.sudo().with_context(planning_slot_generation=True)._planning_slot_generation()

    @api.model
    def _auto_plan_sale_shifts(self, domain, date_from, date_to):
        """Plan the hours of the sales orders over the period, on the employees
        having the role of the service (the least planned first), in their free
        working time.

        :return: (number of shifts to plan, hours planned)
        """
        date_from = max(fields.Datetime.to_datetime(date_from), fields.Datetime.now().replace(second=0, microsecond=0))
        date_to = fields.Datetime.to_datetime(date_to)
        to_plan = self.search(Domain(domain or []) & Domain('is_to_plan', '=', True), order='sale_order_id, id')
        if date_from >= date_to:
            return len(to_plan), 0.0
        planned = defaultdict(float)
        for slot in self.search([('resource_id', '!=', False), ('date_start', '<', date_to), ('date_end', '>', date_from)]):
            planned[slot.resource_id.id] += slot.allocated_hours
        total = 0.0
        for slot in to_plan:
            # Only the employees with the role of the service.
            candidates = slot.role_id.resource_ids.filtered(
                lambda e: e.company_id in (slot.company_id, self.env['res.company']))
            for employee in candidates.sorted(lambda e: (planned[e.id], e.name or '')):
                if not slot.exists():
                    break
                try:
                    with self.env.cr.savepoint():
                        shifts = slot._plan_hours(employee, date_from, date_to)
                except (ValidationError, UserError):
                    continue
                hours = sum(shifts.mapped('allocated_hours'))
                planned[employee.id] += hours
                total += hours
        return len(to_plan), total

    # -------------------------------------------------------------------------
    # SCHEDULE ACTIONS (Publish, Copy previous, Auto plan)
    # -------------------------------------------------------------------------

    @api.model
    def _check_planning_manager(self):
        if not self.env.user.has_group('hudson_planning.group_planning_manager'):
            raise AccessError(_("Only Planning administrators can do this."))

    @api.model
    def action_publish_period(self, domain, date_from, date_to):
        """Publish the draft shifts of the period."""
        self._check_planning_manager()
        slots = self.search(Domain(domain or []) & Domain([
            ('state', '=', 'draft'), ('date_start', '<', date_to), ('date_end', '>', date_from),
        ]))
        slots.action_publish()
        return len(slots)

    def _can_copy_to_next_period(self):
        """Whether the shift is repeated by "Copy previous week"."""
        self.ensure_one()
        return True

    @api.model
    def action_copy_previous_period(self, domain, date_from, date_to, previous_from):
        """Copy the shifts of the previous period into this one, as drafts.

        A shift whose resource is not available anymore becomes an open shift.
        """
        self._check_planning_manager()
        delta = fields.Datetime.to_datetime(date_from) - fields.Datetime.to_datetime(previous_from)
        previous = self.search(Domain(domain or []) & Domain([
            ('date_start', '>=', previous_from), ('date_start', '<', date_from),
        ])).filtered(lambda s: s._can_copy_to_next_period())
        copied = self.browse()
        for slot in previous:
            vals = {
                'date_start': slot.date_start + delta,
                'date_end': slot.date_end + delta,
                'state': 'draft',
                'request_to_switch': False,
            }
            if self.search_count([
                ('resource_id', '=', slot.resource_id.id),
                ('date_start', '=', vals['date_start']),
                ('date_end', '=', vals['date_end']),
            ]):
                continue  # already copied
            try:
                with self.env.cr.savepoint():
                    copied |= slot.copy(vals)
            except ValidationError:
                copied |= slot.copy(dict(vals, resource_id=False))
        return len(copied)

    @api.model
    def action_auto_plan(self, domain, date_from, date_to):
        """Assign the open shifts of the period to available resources: having
        the shift's role, working that day and not booked, the least planned first."""
        self._check_planning_manager()
        open_slots = self.search(Domain(domain or []) & Domain([
            ('resource_id', '=', False), ('date_start', '<', date_to), ('date_end', '>', date_from),
        ]))
        all_employees = self.env['hr.employee'].search([('company_id', 'in', self.env.companies.ids + [False])])
        planned = defaultdict(float)
        for slot in self.search([('resource_id', '!=', False), ('date_start', '<', date_to), ('date_end', '>', date_from)]):
            planned[slot.resource_id.id] += slot.allocated_hours
        assigned = 0
        for slot in open_slots:
            candidates = (slot.role_id.resource_ids or all_employees).filtered(
                lambda e: not slot.company_id or e.company_id in (slot.company_id, self.env['res.company']))
            for employee in candidates.sorted(lambda e: planned[e.id]):
                if not employee._is_available_for_slot(slot):
                    continue
                try:
                    with self.env.cr.savepoint():
                        slot.write({'resource_id': employee.id})
                except (ValidationError, UserError):
                    continue
                planned[employee.id] += slot.allocated_hours
                assigned += 1
                break
        sale_to_plan, sale_hours = self._auto_plan_sale_shifts(domain, date_from, date_to)
        return {'assigned': assigned, 'open': len(open_slots), 'sale_to_plan': sale_to_plan, 'sale_hours': sale_hours}

    def get_popover_data(self):
        """Summary of the shift shown when it is clicked on the schedule.

        ``actions`` are buttons calling a method of the shift; modules add
        their own (see ``_get_popover_actions``).
        """
        self.ensure_one()
        lines = []
        partner = self.partner_id
        if partner:
            address = partner._display_address(without_name=True).strip()
            lines.append({'icon': 'person', 'text': f"{partner.display_name}\n{address}" if address else partner.display_name})
            if partner.phone:
                lines.append({'icon': 'call', 'text': partner.phone})
        for icon, record in (('folder', self.project_id), ('task_alt', self.task_id),
                             ('shopping_cart', self.sale_order_id), ('badge', self.role_id)):
            if record:
                lines.append({'icon': icon, 'text': record.display_name})
        if self.note:
            lines.append({'icon': 'sticky_note_2', 'text': self.note})
        return {
            'id': self.id,
            'name': self.name or '',
            'date_start': fields.Datetime.to_string(self.date_start),
            'date_end': fields.Datetime.to_string(self.date_end),
            'allocated_hours': self.allocated_hours,
            'state': self.state,
            'resource_id': self.resource_id.id,
            'resource_name': self.resource_id.name or '',
            'lines': lines,
            'priority': False,
            'actions': self._get_popover_actions(),
            'can_delete': self.env.user.has_group('hudson_planning.group_planning_manager'),
        }

    def _get_popover_actions(self):
        """Buttons of the schedule popover: ``{'method', 'string'}``, plus
        ``'geolocate': True`` to pass the browser location to the method."""
        return []

    # -------------------------------------------------------------------------
    # TEMPLATES
    # -------------------------------------------------------------------------

    def _get_slot_tz(self):
        self.ensure_one()
        return pytz.timezone(self.resource_id.tz or self.env.user.tz or 'UTC')

    @api.onchange('shift_template_id')
    def _onchange_shift_template_id(self):
        template = self.shift_template_id
        if not template:
            return
        tz = self._get_slot_tz()
        day = fields.Datetime.context_timestamp(self.with_context(tz=tz.zone), self.date_start).date() \
            if self.date_start else fields.Date.context_today(self)
        self.date_start, self.date_end = template._get_interval(day, tz, self.resource_id.resource_calendar_id)
        if template.role_id:
            self.role_id = template.role_id
        if template.project_id:
            self.project_id = template.project_id
        if template.task_id:
            self.task_id = template.task_id

    @api.model_create_multi
    def create(self, vals_list):
        slots = super().create(vals_list)
        slots.filtered('template_creation')._create_shift_template()
        slots.filtered('sale_line_id')._update_sale_hours_to_plan()
        return slots

    def _get_employee_writable_fields(self):
        """Fields employees may change on their shifts: the planning itself
        (resource, dates, state...) is the administrators'."""
        return set()

    def _check_employee_write(self, vals):
        if self.env.su or self.env.user.has_group('hudson_planning.group_planning_manager'):
            return
        forbidden = set(vals) - self._get_employee_writable_fields()
        if forbidden:
            fields_desc = ', '.join(sorted(self._fields[f].string for f in forbidden if f in self._fields))
            raise AccessError(_("Only Planning administrators can change the planning (%s).", fields_desc))

    # Changing them changes the hours left to plan of the sales order line.
    _SALE_PLANNING_FIELDS = {'date_start', 'date_end', 'break_hours', 'allocated_hours', 'sale_line_id', 'active'}

    def write(self, vals):
        self._check_employee_write(vals)
        old_lines = self.sale_line_id
        res = super().write(vals)
        if vals.get('template_creation'):
            self.filtered('template_creation')._create_shift_template()
        if self._SALE_PLANNING_FIELDS & vals.keys():
            self._update_sale_hours_to_plan(old_lines)
        return res

    def unlink(self):
        lines = self.sale_line_id
        res = super().unlink()
        # The hours of a deleted shift are to plan again.
        self.browse()._update_sale_hours_to_plan(lines)
        return res

    def _create_shift_template(self):
        """Save the hours, role and project of the shifts as templates (once)."""
        Template = self.env['fs.shift.template']
        for slot in self.filtered('date_start'):
            tz = slot._get_slot_tz()
            start = pytz.utc.localize(slot.date_start).astimezone(tz)
            end = pytz.utc.localize(slot.date_end).astimezone(tz)
            vals = {
                'start_time': start.hour + start.minute / 60.0,
                'end_time': end.hour + end.minute / 60.0,
                'duration_days': max((end.date() - start.date()).days + (1 if end.time() > start.time() else 0), 1),
                'role_id': slot.role_id.id,
                'project_id': slot.project_id.id,
                'task_id': slot.task_id.id,
                'company_id': slot.company_id.id,
                **slot._get_shift_template_extra_values(),
            }
            template = Template.search([(f, '=', v) for f, v in vals.items()], limit=1) or Template.create(vals)
            super(FsPlanningSlot, slot).write({'template_creation': False, 'shift_template_id': template.id})

    def _get_shift_template_extra_values(self):
        """Values saved on the template created from the shift ("Save as Template")."""
        return {}

    @api.onchange('project_id')
    def _onchange_project_id(self):
        """Fetch the customer and sales order of the project."""
        project = self.project_id
        if self.task_id and self.task_id.project_id != project:
            self.task_id = False
        if not project:
            return
        if project.partner_id:
            self.partner_id = project.partner_id
        # sale_project: project sold through a sales order
        if 'sale_order_id' in project._fields and project.sale_order_id:
            self.sale_order_id = project.sale_order_id

    @api.onchange('task_id')
    def _onchange_task_id(self):
        """Fetch the project, customer and sales order of the task."""
        task = self.task_id
        if not task:
            return
        if task.project_id and task.project_id != self.project_id:
            self.project_id = task.project_id
            self._onchange_project_id()
        if task.partner_id:
            self.partner_id = task.partner_id
        # sale_project: task sold through a sales order line
        if 'sale_line_id' in task._fields and task.sale_line_id:
            self.sale_order_id = task.sale_line_id.order_id

    @api.onchange('role_id')
    def _onchange_role_id(self):
        if self.role_id and self.resource_id:
            if self.resource_id not in self.role_id.resource_ids:
                self.resource_id = False

    # -------------------------------------------------------------------------
    # SHIFT CHANGES (Settings > Shift Changes)
    # -------------------------------------------------------------------------

    def action_request_switch(self):
        """Ask to be replaced: the shift is offered to the other employees."""
        for slot in self:
            if not slot.can_request_switch:
                raise UserError(_("You can only ask for a replacement on your own upcoming published shifts."))
            # sudo: employees cannot write on shifts; checked above
            slot.sudo().request_to_switch = True
            slot.message_post(body=_("%s asked for a replacement on this shift.", self.env.user.name))
        return True

    def action_cancel_switch(self):
        for slot in self:
            if not (slot.is_own_shift or self.env.user.has_group('hudson_planning.group_planning_manager')):
                raise UserError(_("Only the employee of the shift can cancel the replacement request."))
            slot.sudo().request_to_switch = False
        return True

    def action_self_unassign(self):
        """Remove yourself from the shift, which becomes an open shift."""
        for slot in self:
            if not slot.can_self_unassign:
                raise UserError(_("You can only remove yourself from your own upcoming published shifts."))
            # sudo: employees may not write on the shift anymore once unassigned.
            slot.sudo().write({'resource_id': False, 'request_to_switch': False})
            slot.sudo().message_post(body=_("%s removed themselves from this shift.", self.env.user.name))
        return True

    def action_take_shift(self):
        """Take a shift whose employee asked for a replacement."""
        employee = self.env.user.employee_id
        for slot in self:
            if not slot.can_take_shift:
                raise UserError(_("This shift is not offered for replacement."))
            previous = slot.resource_id
            # sudo: the shift belongs to another employee; the overlap check still applies.
            slot.sudo().write({'resource_id': employee.id, 'request_to_switch': False})
            slot.sudo().message_post(body=_(
                "%(new)s replaced %(old)s on this shift.", new=employee.name, old=previous.name,
            ))
        return True

    def action_publish(self):
        self.write({'state': 'published'})
        return True

    def action_unpublish(self):
        self.write({'state': 'draft'})


