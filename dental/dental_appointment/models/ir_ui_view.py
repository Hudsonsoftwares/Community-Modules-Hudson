# -*- coding: utf-8 -*-
"""Registers the ``dental_gantt`` view type: a Gantt-style planning board that shows
appointments as bars on a timeline, one row per doctor (Odoo Community has no
Gantt view, the Enterprise ``web_gantt`` module is not available)."""
from lxml import etree

from odoo import _, fields, models

DENTAL_GANTT_VALID_ATTRIBUTES = {
    '__validate__',  # ir.ui.view implementation detail
    'class',
    'js_class',
    'string',
    'create',
    'edit',
    'date_start',
    'date_stop',
    'resource_field',
    'color_field',
    'default_scale',
    'day_start_hour',
    'day_end_hour',
    'draggable_states',
}
DENTAL_GANTT_FIELD_ATTRIBUTES = ('date_start', 'date_stop', 'resource_field', 'color_field')


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    type = fields.Selection(selection_add=[('dental_gantt', 'Gantt')], ondelete={'dental_gantt': 'cascade'})

    def _get_view_info(self):
        return {'dental_gantt': {'icon': 'calendar_clock'}} | super()._get_view_info()

    def _postprocess_tag_dental_gantt(self, node, name_manager, node_info):
        # Make the fields referenced by attributes available to the web client
        for attribute in DENTAL_GANTT_FIELD_ATTRIBUTES:
            if fname := node.get(attribute):
                name_manager.has_field(node, fname, node_info)

    def _validate_tag_dental_gantt(self, node, name_manager, node_info):
        if not node_info['validate']:
            return
        for attribute in ('date_start', 'date_stop', 'resource_field'):
            if not node.get(attribute):
                self._raise_view_error(_('The Gantt view requires the "%s" attribute.', attribute), node)
        for attribute in DENTAL_GANTT_FIELD_ATTRIBUTES:
            if fname := node.get(attribute):
                name_manager.has_field(node, fname, node_info)
        for child in node.iterchildren(tag=etree.Element):
            if child.tag != 'field':
                self._raise_view_error(_('A Gantt view can only contain <field> nodes, found a <%s>', child.tag), child)
        remaining = set(node.attrib) - DENTAL_GANTT_VALID_ATTRIBUTES
        if remaining:
            self._raise_view_error(_(
                'Invalid attributes (%(invalid)s) in Gantt view. Attributes must be in (%(valid)s)',
                invalid=', '.join(sorted(remaining)),
                valid=', '.join(sorted(DENTAL_GANTT_VALID_ATTRIBUTES - {'__validate__'})),
            ), node)


class IrActionsAct_WindowView(models.Model):
    _inherit = 'ir.actions.act_window.view'

    view_mode = fields.Selection(selection_add=[('dental_gantt', 'Gantt')], ondelete={'dental_gantt': 'cascade'})
