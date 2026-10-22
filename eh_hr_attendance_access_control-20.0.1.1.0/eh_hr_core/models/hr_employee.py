# -*- coding: utf-8 -*-
"""hr.employee: a grouped read keeps to the field privacy a read keeps to.

The HR platform modules add private data to hr.employee (tax settings, pay
configuration, attendance defaults). The guard below is installed once here
for every one of them that depends on the platform core.
"""
from odoo import api, models
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
