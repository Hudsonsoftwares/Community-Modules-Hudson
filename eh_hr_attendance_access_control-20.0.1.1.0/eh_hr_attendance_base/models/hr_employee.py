# -*- encoding: utf-8 -*-
from odoo import api, fields, models
from odoo.models import parse_read_group_spec


def _check_public_grouping(employees, groupby, aggregates, having, order):
    """Refuse a grouped read of hr.employee that names a field, or a many2one
    path, the caller may not read.

    A caller with read access on hr.employee (HR users) runs a normal query
    whose own field checks apply, so nothing is added for them. For everyone
    else each groupby, aggregate, having and order term is checked hop by hop:
    an hr.employee field must be on the public profile, and a field of any
    other model must pass that model's own field access.
    """
    if employees.env.su or employees.browse().has_access('read'):
        return
    specs = [*groupby, *aggregates]
    specs += [leaf[0] for leaf in having or () if isinstance(leaf, (list, tuple))]
    specs += [term.split()[0] for term in (order or '').split(',') if term.strip()]
    for spec in specs:
        if spec == '__count':
            continue
        fname, path, _aggregate = parse_read_group_spec(spec)
        model = employees
        for name in [fname, *(path.split('.') if path else ())]:
            field = model._fields.get(name)
            if field is None:
                break  # the grouped read itself rejects an unknown field
            if model._name == 'hr.employee':
                model._check_private_fields([name])
                public = model.env['hr.employee.public']
                public.check_field_access(public._fields[name], 'read')
            else:
                model.check_field_access(field, 'read')
            if field.type != 'many2one':
                break  # only a many2one path goes on (a properties path names a property)
            model = model.env[field.comodel_name]


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    eh_consent_ids = fields.One2many(
        'eh.hr.consent',
        'employee_id',
        string='Consent records',
    )
    eh_face_consent_state = fields.Selection(
        [
            ('not_set', 'Not set'),
            ('pending', 'Pending'),
            ('granted', 'Granted'),
            ('withdrawn', 'Withdrawn'),
            ('expired', 'Expired'),
        ],
        string='Face consent',
        compute='_compute_eh_face_consent_state',
        search='_search_eh_face_consent_state',
        store=False,
    )
    eh_kiosk_pin = fields.Char(
        string='Kiosk PIN',
        copy=False,
        groups='eh_hr_attendance_base.group_eh_hr_manager',
        help="Optional fallback PIN used at the kiosk when face match is unavailable. Manager-only field.",
    )
    # Attendance configuration of the employee, restricted to HR users as core
    # restricts its own private employee fields (EH Attendance Manager and
    # Admin reach HR User through HR Administrator; EH Attendance User and
    # Auditor do not). People outside HR read the public employee profile,
    # and a field they may not read stays out of their prefetch. The kiosk
    # and mobile endpoints read the employee as superuser once the device
    # token is checked.
    eh_kiosk_site_default_id = fields.Many2one(
        'eh.hr.kiosk.site',
        string='Default kiosk site',
        groups='hr.group_hr_user',
        help="Suggested site for this employee. Other sites still accept this employee unless their record rules forbid it.",
    )
    eh_face_enrolled = fields.Boolean(
        string='Face enrolled',
        default=False,
        copy=False,
        groups='hr.group_hr_user',
        help="Set to True by the face kiosk module once at least one face template has been stored. Reset on consent withdrawal.",
    )

    @api.depends('eh_consent_ids.consent_type', 'eh_consent_ids.state')
    def _compute_eh_face_consent_state(self):
        for employee in self:
            face_consents = employee.eh_consent_ids.filtered(lambda c: c.consent_type == 'face')
            if not face_consents:
                employee.eh_face_consent_state = 'not_set'
                continue
            sorted_consents = face_consents.sorted(key=lambda c: c.create_date or fields.Datetime.now(), reverse=True)
            latest = sorted_consents[0]
            employee.eh_face_consent_state = latest.state

    def _search_eh_face_consent_state(self, operator, value):
        if operator not in ('=', '!=', 'in', 'not in'):
            return [('id', 'in', [])]
        if isinstance(value, str):
            values = [value]
        else:
            values = list(value)
        if 'not_set' in values:
            employees_with_face = self.env['eh.hr.consent'].search([
                ('consent_type', '=', 'face'),
            ]).mapped('employee_id.id')
            if operator in ('=', 'in'):
                return [('id', 'not in', employees_with_face)]
            else:
                return [('id', 'in', employees_with_face)]
        consents = self.env['eh.hr.consent'].search([
            ('consent_type', '=', 'face'),
            ('state', 'in', values),
        ])
        employee_ids = consents.mapped('employee_id.id')
        if operator in ('=', 'in'):
            return [('id', 'in', employee_ids)]
        else:
            return [('id', 'not in', employee_ids)]

    # hr.employee hides its private fields from people outside HR in fetch and
    # search_fetch only. A grouped read (list group by, pivot, graph, or a
    # direct formatted_read_group call) runs on the query hr.employee._search
    # returns for them, which is built as superuser, so neither the field
    # groups nor the public profile are checked, and a private value such as
    # a tax number or its ciphertext would come back as a group key or an
    # aggregate. The grouped read applies the rule fetch applies: outside HR,
    # only what hr.employee.public exposes.
    #
    # The guard sits once in the root of each product line that adds private
    # employee data, the module every other module of the line depends on:
    # eh_hr_core, eh_hr_attendance_base (the attendance line installs without
    # the platform core), eh_hero_hr, eh_hero_onboarding (it installs without
    # eh_hero_hr) and eh_l10n_ie_hr_payroll. Keep those copies identical. When
    # two lines are installed together the check simply runs twice.
    @api.model
    def _read_group(self, domain, groupby=(), aggregates=(), having=(),
                    offset=0, limit=None, order=None):
        _check_public_grouping(self, groupby, aggregates, having, order)
        return super()._read_group(
            domain, groupby, aggregates, having, offset, limit, order)

    @api.model
    def _read_grouping_sets(self, domain, grouping_sets, aggregates=(), order=None):
        _check_public_grouping(
            self, [spec for groupby in grouping_sets for spec in groupby],
            aggregates, (), order)
        return super()._read_grouping_sets(domain, grouping_sets, aggregates, order)

    # Every grouped term has its field access checked in Field.to_sql, except
    # a many2many group by: it is built from the relation table
    # (field.join(table, only_ids=True)) and never reaches to_sql. A user who
    # may read hr.employee but not a many2many restricted with groups= (an
    # administrator outside HR) would get its values back as group keys, so
    # the check is made here. It also covers a group by that reaches
    # hr.employee through a many2one path from another model. For people
    # outside HR a grouped read of hr.employee itself runs on the superuser
    # query, where this check passes: _check_public_grouping refuses them.
    def _read_group_groupby(self, table, groupby_spec):
        fname = parse_read_group_spec(groupby_spec)[0]
        field = self._fields.get(fname)
        if field is not None and field.type == 'many2many':
            table._model.check_field_access(field, 'read')
        return super()._read_group_groupby(table, groupby_spec)
