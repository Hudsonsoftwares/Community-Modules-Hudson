import re
from datetime import datetime, time

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

ROOM_TYPES = [
    ('reception', 'Reception'),
    ('waiting', 'Waiting Area'),
    ('operatory', 'Dental Operatory'),
    ('consultation', 'Consultation Room'),
    ('radiology', 'Radiology (X-Ray)'),
    ('laboratory', 'Laboratory'),
    ('pharmacy', 'Pharmacy'),
    ('sterilization', 'Sterilization'),
    ('store', 'Store Room'),
    ('office', 'Office'),
    ('washroom', 'Washroom'),
    ('other', 'Other'),
]

ROOM_COLORS = {
    'reception': '#dbeafe', 'waiting': '#ede9fe', 'operatory': '#cffafe', 'consultation': '#dcfce7',
    'radiology': '#ccfbf1', 'laboratory': '#fef3c7', 'pharmacy': '#ffe4e6', 'sterilization': '#d1fae5',
    'store': '#f1f5f9', 'office': '#e0e7ff', 'washroom': '#f0f9ff', 'other': '#f8fafc',
}

# Live elements an administrator can place on the floor plan.
# 'models': all must exist (i.e. the module is installed) for the element to be offered.
ELEMENT_CATALOG = [
    {'key': 'reception', 'label': 'Reception', 'icon': 'fa-user-circle-o', 'color': '#2563eb',
     'models': ['dental.appointment'], 'action': 'dental_appointment.action_dental_patient_checkin',
     'description': 'Patients checked in and waiting'},
    {'key': 'appointments', 'label': 'OPD / Appointments', 'icon': 'fa-calendar-check-o', 'color': '#7c3aed',
     'models': ['dental.appointment'], 'action': 'dental_appointment.action_dental_appointment_queue',
     'description': "Today's appointments"},
    {'key': 'chairs', 'label': 'Dental Chairs', 'icon': 'fa-user-md', 'color': '#0891b2',
     'models': ['dental.appointment'], 'action': False,
     'description': 'Chairs in use (patients in consultation)'},
    {'key': 'clinical', 'label': 'Clinical Cases', 'icon': 'fa-stethoscope', 'color': '#16a34a',
     'models': ['dental.case'], 'action': 'dental_core.action_dental_case',
     'description': 'Open clinical cases'},
    {'key': 'radiology', 'label': 'Radiology (X-Ray)', 'icon': 'fa-picture-o', 'color': '#0d9488',
     'models': ['dental.case'], 'action': 'dental_core.action_dental_clinical_images',
     'description': 'Clinical images added today'},
    {'key': 'laboratory', 'label': 'Laboratory', 'icon': 'fa-flask', 'color': '#d97706',
     'models': ['dental.lab.order'], 'action': 'dental_lab.action_dental_lab_orders',
     'description': 'Lab orders in progress'},
    {'key': 'pharmacy', 'label': 'Pharmacy', 'icon': 'fa-medkit', 'color': '#e11d48',
     'models': ['dental.prescription'], 'action': 'dental_pharmacy.action_dental_prescription_pending',
     'description': 'Prescriptions waiting to be dispensed'},
    {'key': 'equipment', 'label': 'Equipment & Sterilization', 'icon': 'fa-wrench', 'color': '#059669',
     'models': ['maintenance.request'], 'action': 'dental_core.action_dental_maintenance_dashboard',
     'description': 'Open maintenance requests'},
    {'key': 'billing', 'label': 'Billing Desk', 'icon': 'fa-money', 'color': '#4f46e5',
     'models': ['account.move'], 'action': 'dental_core.action_dental_pending_bills',
     'group': 'account.group_account_invoice', 'description': 'Patient bills awaiting payment'},
    {'key': 'documents', 'label': 'Documents', 'icon': 'fa-folder-open', 'color': '#64748b',
     'models': ['dms.file'], 'action': 'dental_dms.action_dental_document_center',
     'description': 'Patient documents'},
    {'key': 'second_opinion', 'label': 'Second Opinions', 'icon': 'fa-comments', 'color': '#9333ea',
     'models': ['dental.second.opinion'], 'action': 'dental_second_opinion.action_dental_second_opinion',
     'description': 'Second opinion requests in progress'},
]

# Static equipment / furniture an administrator can place on the floor plan. The icons are drawn in
# static/src/js/floor_plan_icons.js under the same keys; they can also replace a live element's icon.
FIXTURE_CATEGORIES = [
    ('clinical', 'Clinical'),
    ('imaging', 'Imaging'),
    ('sterilization', 'Sterilization & Utilities'),
    ('lab', 'Laboratory'),
    ('furniture', 'Furniture'),
    ('layout', 'Layout & Access'),
    ('safety', 'Safety'),
]

# (key, label, category, default colour, default size in % of the canvas width)
FIXTURE_CATALOG = [
    ('dental_chair', 'Dental Chair', 'clinical', '#0891b2', 6.0),
    ('operating_light', 'Operating Light', 'clinical', '#d97706', 4.0),
    ('instrument_tray', 'Instrument Tray', 'clinical', '#475569', 4.0),
    ('handpiece', 'Handpiece', 'clinical', '#0e7490', 3.5),
    ('dental_mirror', 'Mouth Mirror', 'clinical', '#64748b', 3.5),
    ('syringe', 'Syringe / Anaesthesia', 'clinical', '#2563eb', 3.5),
    ('tooth', 'Tooth', 'clinical', '#0ea5e9', 4.0),
    ('implant', 'Implant', 'clinical', '#6366f1', 4.0),
    ('xray', 'X-Ray Unit', 'imaging', '#0d9488', 5.0),
    ('xray_film', 'Radiograph Viewer', 'imaging', '#0f766e', 4.0),
    ('monitor', 'Computer / Monitor', 'imaging', '#334155', 4.0),
    ('autoclave', 'Autoclave', 'sterilization', '#059669', 5.0),
    ('sink', 'Sink / Scrub Station', 'sterilization', '#0284c7', 4.5),
    ('compressor', 'Compressor / Suction', 'sterilization', '#57534e', 5.0),
    ('waste_bin', 'Bio-Waste Bin', 'sterilization', '#dc2626', 3.5),
    ('microscope', 'Microscope', 'lab', '#d97706', 4.0),
    ('flask', 'Lab Bench', 'lab', '#b45309', 4.0),
    ('reception_desk', 'Reception Desk', 'furniture', '#2563eb', 6.0),
    ('desk', 'Desk', 'furniture', '#78716c', 5.0),
    ('sofa', 'Waiting Sofa', 'furniture', '#7c3aed', 6.0),
    ('chair', 'Chair', 'furniture', '#8b5cf6', 3.5),
    ('cabinet', 'Cabinet / Storage', 'furniture', '#64748b', 4.0),
    ('water_dispenser', 'Water Dispenser', 'furniture', '#0ea5e9', 3.5),
    ('plant', 'Plant', 'furniture', '#16a34a', 3.5),
    ('door', 'Door', 'layout', '#475569', 5.0),
    ('window', 'Window', 'layout', '#0284c7', 5.0),
    ('stairs', 'Stairs', 'layout', '#475569', 5.0),
    ('exit', 'Exit', 'layout', '#16a34a', 4.0),
    ('toilet', 'Washroom', 'layout', '#0284c7', 4.0),
    ('wheelchair', 'Wheelchair Access', 'layout', '#2563eb', 4.0),
    ('fire_extinguisher', 'Fire Extinguisher', 'safety', '#dc2626', 3.5),
    ('first_aid', 'First Aid / Emergency Kit', 'safety', '#e11d48', 4.0),
    ('oxygen', 'Oxygen Cylinder', 'safety', '#16a34a', 3.5),
    ('ac', 'Air Conditioner', 'safety', '#0ea5e9', 5.0),
]
FIXTURE_SPECS = {key: {'key': key, 'label': label, 'category': cat, 'color': color, 'size': size}
                 for key, label, cat, color, size in FIXTURE_CATALOG}

# Layout offered to a clinic that has no floor plan yet: (name, type, x, y, w, h, element keys)
DEFAULT_LAYOUT = [
    ('Waiting Area', 'waiting', 2, 4, 23, 42, ['appointments']),
    ('Dental Operatory', 'operatory', 27, 4, 24, 42, ['chairs']),
    ('Radiology', 'radiology', 53, 4, 20, 42, ['radiology']),
    ('Laboratory', 'laboratory', 75, 4, 23, 42, ['laboratory']),
    ('Reception', 'reception', 2, 52, 25, 44, ['reception', 'billing']),
    ('Consultation', 'consultation', 29, 52, 22, 44, ['clinical']),
    ('Pharmacy', 'pharmacy', 53, 52, 20, 44, ['pharmacy']),
    ('Sterilization', 'sterilization', 75, 52, 23, 44, ['equipment']),
]

# Equipment placed with the standard layout: (fixture key, x, y, live element opened on click)
DEFAULT_FIXTURES = [
    ('sofa', 7, 14, False), ('plant', 21, 12, False), ('water_dispenser', 21, 38, False),
    ('dental_chair', 32, 14, 'chairs'), ('operating_light', 39, 12, False), ('dental_chair', 46, 14, 'chairs'),
    ('instrument_tray', 31, 38, False),
    ('xray', 58, 14, 'radiology'), ('xray_film', 69, 38, 'radiology'),
    ('microscope', 80, 14, 'laboratory'), ('flask', 94, 14, 'laboratory'),
    ('reception_desk', 8, 63, 'reception'), ('door', 5, 89, False), ('wheelchair', 23, 89, False),
    ('desk', 34, 63, False), ('monitor', 47, 63, False),
    ('cabinet', 57, 63, 'pharmacy'), ('first_aid', 69, 89, False),
    ('autoclave', 80, 63, 'equipment'), ('sink', 94, 63, False),
    ('compressor', 80, 89, 'equipment'), ('fire_extinguisher', 94, 89, False),
]


def _clamp(value, low=0.0, high=100.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = low
    return max(low, min(high, value))


class DentalFloorRoom(models.Model):
    _name = 'dental.floor.room'
    _description = 'Clinic Floor Plan Room'
    _order = 'company_id, sequence, id'
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, index=True, default=lambda self: self.env.company,
                                 ondelete='cascade')
    room_type = fields.Selection(ROOM_TYPES, string='Room Type', required=True, default='other')
    color = fields.Char(help='Background colour (hex).')
    sequence = fields.Integer(default=10)
    # Position and size in % of the floor plan canvas
    pos_x = fields.Float(default=40.0)
    pos_y = fields.Float(default=35.0)
    width = fields.Float(default=20.0)
    height = fields.Float(default=25.0)

    @api.constrains('width', 'height')
    def _check_size(self):
        for room in self:
            if room.width <= 0 or room.height <= 0:
                raise ValidationError(_("A room must have a positive width and height."))


class DentalFloorElement(models.Model):
    _name = 'dental.floor.element'
    _description = 'Clinic Floor Plan Live Element'
    _order = 'company_id, id'
    _check_company_auto = True

    element_key = fields.Char(required=True, help='Key of the live element (see the floor plan catalog).')
    label = fields.Char(help='Optional custom label, e.g. "Chairs 1-4".')
    company_id = fields.Many2one('res.company', required=True, index=True, default=lambda self: self.env.company,
                                 ondelete='cascade')
    pos_x = fields.Float(default=50.0)
    pos_y = fields.Float(default=50.0)
    icon = fields.Char(help='Optional icon (key of the dental icon library) replacing the default icon.')
    color = fields.Char(help='Optional accent colour (hex) replacing the default colour.')


class DentalFloorFixture(models.Model):
    _name = 'dental.floor.fixture'
    _description = 'Clinic Floor Plan Equipment'
    _order = 'company_id, sequence, id'
    _check_company_auto = True

    fixture_key = fields.Char(required=True, help='Key of the equipment icon (see the floor plan library).')
    label = fields.Char(help='Optional label shown under the icon, e.g. "Chair 1".')
    company_id = fields.Many2one('res.company', required=True, index=True, default=lambda self: self.env.company,
                                 ondelete='cascade')
    sequence = fields.Integer(default=10)
    pos_x = fields.Float(default=50.0)
    pos_y = fields.Float(default=50.0)
    size = fields.Float(default=4.0, help='Icon size in % of the floor plan width.')
    rotation = fields.Integer(default=0, help='Rotation in degrees.')
    color = fields.Char(help='Icon colour (hex).')
    link_key = fields.Char(help='Live element whose records open when the equipment is clicked on the dashboard.')


def _angle(value):
    try:
        return int(round(float(value))) % 360
    except (TypeError, ValueError, OverflowError):
        return 0


def _hex_color(value):
    value = (value or '').strip()
    return value if re.fullmatch(r'#[0-9a-fA-F]{3,8}', value) else False


class DentalFloorPlan(models.AbstractModel):
    """Floor plan service for the Dental Clinic dashboard (selected clinic = env.company)."""
    _name = 'dental.floor.plan'
    _description = 'Clinic Floor Plan'

    # ---------------------------------------------------------
    # Catalog & live stats
    # ---------------------------------------------------------
    @api.model
    def _available_elements(self):
        """Catalog entries whose modules are installed (and that the user may open)."""
        user = self.env.user
        return [spec for spec in ELEMENT_CATALOG
                if all(model in self.env for model in spec['models'])
                and (not spec.get('group') or user.has_group(spec['group']))]

    @api.model
    def _today_utc_bounds(self, company):
        tz = self.env['dental.appointment']._get_clinic_tz(company)
        today = datetime.now(pytz.utc).astimezone(tz).date()
        start = tz.localize(datetime.combine(today, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        end = tz.localize(datetime.combine(today, time.max)).astimezone(pytz.utc).replace(tzinfo=None)
        return start, end

    @api.model
    def _element_stats(self, company):
        """{key: {'value', 'caption', 'status'}} for the clinic. Counts only (read with sudo, scoped
        to the clinic), so the dashboard works for managers without every module's rights."""
        env = self.env
        start, end = self._today_utc_bounds(company)
        stats = {}
        Appt = env['dental.appointment'].sudo()
        day_domain = Appt._dental_day_domain(start, end) + [('branch_id', '=', company.id)]
        today = Appt.search(day_domain)
        waiting = len(today.filtered(lambda a: a.state == 'checked_in'))
        in_chair = len(today.filtered(lambda a: a.state == 'in_consultation'))
        live = today.filtered(lambda a: a.state not in ('cancelled', 'no_show'))
        chairs = company.dental_chair_count or 0
        stats['reception'] = {'value': waiting, 'caption': _('waiting'), 'status': 'busy' if waiting else 'ok'}
        stats['appointments'] = {'value': len(live), 'caption': _('today'), 'status': 'ok'}
        stats['chairs'] = {'value': '%s / %s' % (in_chair, chairs) if chairs else in_chair, 'caption': _('in use'),
                           'status': 'alert' if chairs and in_chair >= chairs else ('busy' if in_chair else 'ok')}
        if 'dental.case' in env:
            open_cases = env['dental.case'].sudo().search_count(
                [('state', 'in', ('open', 'under_treatment')), ('company_id', '=', company.id)])
            stats['clinical'] = {'value': open_cases, 'caption': _('open cases'), 'status': 'ok'}
            images = env['ir.attachment'].sudo().search_count([
                ('res_model', 'in', ('dental.case', 'dental.clinical.examination', 'dental.treatment.plan')),
                ('create_date', '>=', start), ('create_date', '<=', end), ('company_id', 'in', (company.id, False))])
            stats['radiology'] = {'value': images, 'caption': _('images today'), 'status': 'ok'}
        if 'dental.lab.order' in env:
            lab = env['dental.lab.order'].sudo().search_count([
                ('state', 'in', ('submitted', 'in_production', 'qc_pending', 'rework')), ('company_id', '=', company.id)])
            stats['laboratory'] = {'value': lab, 'caption': _('in progress'), 'status': 'busy' if lab else 'ok'}
        if 'dental.prescription' in env:
            has_pharmacy = company.dental_has_pharmacy if 'dental_has_pharmacy' in company._fields else True
            pending = env['dental.prescription'].sudo().search_count([
                ('state', 'in', ('confirmed', 'partially_dispensed')), ('company_id', '=', company.id)])
            stats['pharmacy'] = ({'value': pending, 'caption': _('to dispense'), 'status': 'busy' if pending else 'ok'}
                                 if has_pharmacy else {'value': _('Off'), 'caption': _('no in-house pharmacy'), 'status': 'idle'})
        if 'maintenance.request' in env:
            requests = env['maintenance.request'].sudo().search_count([
                ('stage_id.fold', '=', False), ('company_id', '=', company.id)])
            stats['equipment'] = {'value': requests, 'caption': _('open requests'), 'status': 'alert' if requests else 'ok'}
        if 'account.move' in env:
            bills = env['account.move'].sudo().search_count([
                ('move_type', '=', 'out_invoice'), ('company_id', '=', company.id),
                ('state', '=', 'posted'), ('payment_state', 'in', ('not_paid', 'partial'))])
            stats['billing'] = {'value': bills, 'caption': _('to collect'), 'status': 'busy' if bills else 'ok'}
        if 'dms.file' in env and 'dental_doc_type' in env['dms.file']._fields:
            docs = env['dms.file'].sudo().search_count([('dental_doc_type', '!=', False)])
            stats['documents'] = {'value': docs, 'caption': _('documents'), 'status': 'ok'}
        if 'dental.second.opinion' in env:
            opinions = env['dental.second.opinion'].sudo().search_count([
                ('state', 'in', ('submitted', 'in_review', 'info_requested', 'opinion_submitted', 'clarification')),
                ('company_id', '=', company.id)])
            stats['second_opinion'] = {'value': opinions, 'caption': _('in progress'), 'status': 'ok'}
        return stats

    # ---------------------------------------------------------
    # API for the dashboard
    # ---------------------------------------------------------
    @api.model
    def _can_edit(self):
        return self.env.user.has_group('dental_base.group_dental_admin')

    @api.model
    def get_floor_plan(self):
        company = self.env.company
        available = self._available_elements()
        catalog = {spec['key']: spec for spec in available}
        stats = self._element_stats(company)
        rooms = self.env['dental.floor.room'].sudo().search([('company_id', '=', company.id)])
        elements = self.env['dental.floor.element'].sudo().search([('company_id', '=', company.id)])
        fixtures = self.env['dental.floor.fixture'].sudo().search([('company_id', '=', company.id)])
        room_type_labels = dict(ROOM_TYPES)
        category_labels = dict(FIXTURE_CATEGORIES)
        return {
            'company': {'id': company.id, 'name': company.name},
            'can_edit': self._can_edit(),
            'background_url': (f'/web/image/res.company/{company.id}/dental_floor_plan_image'
                               if company.sudo().dental_floor_plan_image else False),
            'room_types': [{'key': k, 'label': v, 'color': ROOM_COLORS[k]} for k, v in ROOM_TYPES],
            'palette': [{k: spec[k] for k in ('key', 'label', 'icon', 'color', 'description')} for spec in available],
            'fixture_categories': [{'key': k, 'label': v} for k, v in FIXTURE_CATEGORIES],
            'fixture_catalog': [dict(spec, category_label=category_labels[spec['category']])
                                for spec in FIXTURE_SPECS.values()],
            'rooms': [{
                'id': r.id, 'name': r.name, 'room_type': r.room_type,
                'type_label': room_type_labels.get(r.room_type, ''),
                'color': r.color or ROOM_COLORS.get(r.room_type, '#f8fafc'),
                'x': r.pos_x, 'y': r.pos_y, 'w': r.width, 'h': r.height,
            } for r in rooms],
            # Elements of modules that were uninstalled are kept but not shown
            'elements': [{
                'id': e.id, 'key': e.element_key,
                'label': e.label or catalog[e.element_key]['label'],
                'custom_label': e.label or '',
                'icon': catalog[e.element_key]['icon'],
                'svg': e.icon if e.icon in FIXTURE_SPECS else False,
                'color': e.color or catalog[e.element_key]['color'],
                'custom_color': e.color or '',
                'x': e.pos_x, 'y': e.pos_y,
                **stats.get(e.element_key, {'value': '', 'caption': '', 'status': 'idle'}),
            } for e in elements if e.element_key in catalog],
            'fixtures': [{
                'id': f.id, 'key': f.fixture_key, 'label': f.label or '',
                'name': FIXTURE_SPECS[f.fixture_key]['label'],
                'x': f.pos_x, 'y': f.pos_y, 'size': f.size, 'rotation': f.rotation,
                'color': f.color or FIXTURE_SPECS[f.fixture_key]['color'],
                # A link to the live element of an uninstalled module is not offered
                'link_key': f.link_key if f.link_key in catalog else False,
                # Live status of the linked element (e.g. chairs busy), shown as a dot on the equipment
                'status': stats.get(f.link_key, {}).get('status', 'idle') if f.link_key in catalog else False,
            } for f in fixtures if f.fixture_key in FIXTURE_SPECS],
        }

    @api.model
    def save_floor_plan(self, rooms, elements, fixtures=None):
        """Replace the selected clinic's layout with the one edited on the dashboard.
        The equipment (``fixtures``) is left unchanged when not given."""
        if not self._can_edit():
            raise AccessError(_("Only Dental Administrators can change the clinic floor plan."))
        company = self.env.company
        valid_keys = {spec['key'] for spec in ELEMENT_CATALOG}
        valid_types = dict(ROOM_TYPES)
        Room = self.env['dental.floor.room']
        Element = self.env['dental.floor.element']

        kept_rooms = Room.browse()
        existing_rooms = Room.search([('company_id', '=', company.id)])
        for seq, data in enumerate(rooms or []):
            vals = {
                'name': (data.get('name') or _('Room')).strip()[:64],
                'room_type': data.get('room_type') if data.get('room_type') in valid_types else 'other',
                'color': (data.get('color') or '')[:16] or False,
                'sequence': seq,
                'pos_x': _clamp(data.get('x')), 'pos_y': _clamp(data.get('y')),
                'width': _clamp(data.get('w'), 2.0), 'height': _clamp(data.get('h'), 2.0),
            }
            room = existing_rooms.filtered(lambda r: r.id == data.get('id'))
            if room:
                room.write(vals)
            else:
                room = Room.create(dict(vals, company_id=company.id))
            kept_rooms |= room
        (existing_rooms - kept_rooms).unlink()

        kept_elements = Element.browse()
        existing_elements = Element.search([('company_id', '=', company.id)])
        for data in elements or []:
            if data.get('key') not in valid_keys:
                continue
            vals = {'element_key': data['key'], 'pos_x': _clamp(data.get('x')), 'pos_y': _clamp(data.get('y')),
                    'label': (data.get('custom_label') or '').strip()[:64] or False,
                    'icon': data.get('svg') if data.get('svg') in FIXTURE_SPECS else False,
                    'color': _hex_color(data.get('custom_color'))}
            element = existing_elements.filtered(lambda e: e.id == data.get('id'))
            if element:
                element.write(vals)
            else:
                element = Element.create(dict(vals, company_id=company.id))
            kept_elements |= element
        # Elements of uninstalled modules are not on the dashboard, so they are not removed here
        hidden = existing_elements.filtered(lambda e: e.element_key not in {s['key'] for s in self._available_elements()})
        (existing_elements - kept_elements - hidden).unlink()

        if fixtures is not None:
            Fixture = self.env['dental.floor.fixture']
            kept_fixtures = Fixture.browse()
            existing_fixtures = Fixture.search([('company_id', '=', company.id)])
            for seq, data in enumerate(fixtures):
                spec = FIXTURE_SPECS.get(data.get('key'))
                if not spec:
                    continue
                vals = {
                    'fixture_key': spec['key'], 'sequence': seq,
                    'label': (data.get('label') or '').strip()[:64] or False,
                    'pos_x': _clamp(data.get('x')), 'pos_y': _clamp(data.get('y')),
                    'size': _clamp(data.get('size') or spec['size'], 1.5, 25.0),
                    'rotation': _angle(data.get('rotation')),
                    'color': _hex_color(data.get('color')),
                    'link_key': data.get('link_key') if data.get('link_key') in valid_keys else False,
                }
                fixture = existing_fixtures.filtered(lambda f: f.id == data.get('id'))
                if fixture:
                    fixture.write(vals)
                else:
                    fixture = Fixture.create(dict(vals, company_id=company.id))
                kept_fixtures |= fixture
            (existing_fixtures - kept_fixtures).unlink()
        return self.get_floor_plan()

    @api.model
    def load_default_floor_plan(self):
        """Start the selected clinic from a standard layout (only the installed modules' elements)."""
        if not self._can_edit():
            raise AccessError(_("Only Dental Administrators can change the clinic floor plan."))
        company = self.env.company
        self.env['dental.floor.room'].search([('company_id', '=', company.id)]).unlink()
        self.env['dental.floor.element'].search([('company_id', '=', company.id)]).unlink()
        self.env['dental.floor.fixture'].search([('company_id', '=', company.id)]).unlink()
        available = {spec['key'] for spec in self._available_elements()}
        for seq, (name, room_type, x, y, w, h, keys) in enumerate(DEFAULT_LAYOUT):
            keys = [k for k in keys if k in available]
            self.env['dental.floor.room'].create({
                'name': name, 'room_type': room_type, 'company_id': company.id, 'sequence': seq,
                'pos_x': x, 'pos_y': y, 'width': w, 'height': h,
            })
            for idx, key in enumerate(keys):
                offset = (idx - (len(keys) - 1) / 2.0) * 9.0
                self.env['dental.floor.element'].create({
                    'element_key': key, 'company_id': company.id,
                    'pos_x': x + w / 2.0 + offset * w / 25.0, 'pos_y': y + h / 2.0,
                })
        for seq, (key, x, y, link) in enumerate(DEFAULT_FIXTURES):
            self.env['dental.floor.fixture'].create({
                'fixture_key': key, 'company_id': company.id, 'sequence': seq,
                'pos_x': x, 'pos_y': y, 'size': FIXTURE_SPECS[key]['size'],
                'link_key': link if link in available else False,
            })
        return self.get_floor_plan()

    @api.model
    def action_open_element(self, key):
        spec = next((s for s in self._available_elements() if s['key'] == key), None)
        if not spec:
            raise AccessError(_("This element is not available."))
        if key == 'chairs':
            return {
                'type': 'ir.actions.act_window',
                'name': _('Patients in the Chair'),
                'res_model': 'dental.appointment',
                'views': [(False, 'list'), (False, 'form')],
                'domain': [('state', '=', 'in_consultation'), ('branch_id', '=', self.env.company.id)],
            }
        return self.env['ir.actions.actions']._for_xml_id(spec['action'])
