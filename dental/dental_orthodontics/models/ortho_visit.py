from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Common archwire sequence, light round NiTi -> rectangular NiTi -> rectangular stainless steel / TMA
WIRES = [
    ('niti_012', '0.012" NiTi'),
    ('niti_014', '0.014" NiTi'),
    ('niti_016', '0.016" NiTi'),
    ('niti_018', '0.018" NiTi'),
    ('niti_14x25', '0.014×0.025" NiTi'),
    ('niti_16x22', '0.016×0.022" NiTi'),
    ('niti_17x25', '0.017×0.025" NiTi'),
    ('niti_18x25', '0.018×0.025" NiTi'),
    ('niti_19x25', '0.019×0.025" NiTi'),
    ('ss_016', '0.016" SS'),
    ('ss_018', '0.018" SS'),
    ('ss_020', '0.020" SS'),
    ('ss_16x22', '0.016×0.022" SS'),
    ('ss_17x25', '0.017×0.025" SS'),
    ('ss_19x25', '0.019×0.025" SS'),
    ('tma_17x25', '0.017×0.025" TMA'),
    ('tma_19x25', '0.019×0.025" TMA'),
    ('braided_ss', 'Braided SS (finishing)'),
    ('other', 'Other'),
]


class DentalOrthoVisit(models.Model):
    """One orthodontic appointment: what was done to the appliances and what the patient must do next."""
    _name = 'dental.ortho.visit'
    _description = 'Orthodontic Visit'
    _inherit = ['mail.thread', 'dental.company.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Visit', compute='_compute_name', store=True)
    chart_id = fields.Many2one('dental.ortho.chart', string='Orthodontic Chart', required=True, index=True,
                               ondelete='cascade', check_company=True)
    patient_id = fields.Many2one(related='chart_id.patient_id', store=True, index=True, string='Patient')
    case_id = fields.Many2one(related='chart_id.case_id', store=True, string='Dental Case')
    appointment_id = fields.Many2one('dental.appointment', string='Appointment', check_company=True,
                                     domain="[('patient_id', '=', patient_id)]")
    doctor_id = fields.Many2one('hr.employee.public', string='Orthodontist')
    date = fields.Datetime(string='Date', required=True, default=fields.Datetime.now)
    state = fields.Selection([('draft', 'In Progress'), ('done', 'Done'), ('cancelled', 'Cancelled')],
                             string='Status', default='draft', required=True, tracking=True, copy=False)
    visit_type = fields.Selection([
        ('records', 'Records (Photos, Impressions / Scan, X-rays)'),
        ('bonding', 'Bonding / Appliance Fitting'),
        ('adjustment', 'Adjustment / Wire Change'),
        ('emergency', 'Emergency (Broken Bracket, Poking Wire)'),
        ('debond', 'Debond & Retainer Fitting'),
        ('retention_check', 'Retention Check'),
    ], string='Visit Type', default='adjustment', required=True)
    visit_number = fields.Integer(string='Visit No.', compute='_compute_name', store=True)

    # Wires
    upper_wire = fields.Selection(WIRES, string='Upper Archwire')
    lower_wire = fields.Selection(WIRES, string='Lower Archwire')
    upper_wire_changed = fields.Boolean(string='Upper Wire Changed', compute='_compute_wire_changes', store=True)
    lower_wire_changed = fields.Boolean(string='Lower Wire Changed', compute='_compute_wire_changes', store=True)
    wire_notes = fields.Char(string='Wire Bends / Steps', help='e.g. Step-down 12, reverse curve lower, tie-back')
    ligation = fields.Selection([('elastomeric', 'Elastomeric Modules'), ('steel', 'Steel Ligatures'),
                                 ('self_ligating', 'Self-ligating (clip)')], string='Ligation')
    power_chain = fields.Char(string='Power Chain', help='Where, e.g. 13-23 upper, 33-43 lower')
    springs = fields.Char(string='Springs', help='Open / closed coil springs, e.g. open coil 12-14')

    # Elastics (patient instructions)
    elastics = fields.Selection([
        ('none', 'None'),
        ('class_2', 'Class II'),
        ('class_3', 'Class III'),
        ('vertical', 'Vertical / Box'),
        ('triangle', 'Triangle'),
        ('cross', 'Cross Elastics'),
        ('midline', 'Midline'),
    ], string='Elastics', default='none')
    elastic_size = fields.Char(string='Elastic Size / Force', help='e.g. 3/16" 3.5 oz')
    elastic_wear = fields.Selection([('fulltime', 'Full-time (22 h)'), ('nights', 'Nights Only')], string='Elastic Wear')

    # Aligners
    aligner_tray = fields.Integer(string='Aligner Tray No.')
    aligner_total = fields.Integer(string='Total Trays')

    # Procedures and assessment
    rebond_teeth = fields.Char(string='Brackets Re-bonded', help='FDI numbers')
    ipr = fields.Char(string='IPR (mm)', help='Interproximal reduction, e.g. 0.2 mm 31/41')
    procedures = fields.Text(string='Other Procedures')
    hygiene = fields.Selection([('good', 'Good'), ('fair', 'Fair'), ('poor', 'Poor')], string='Oral Hygiene')
    compliance = fields.Selection([('good', 'Good'), ('fair', 'Fair'), ('poor', 'Poor')], string='Compliance',
                                  help='Wear of elastics / aligners and following instructions.')
    progress_notes = fields.Text(string='Progress Notes')
    patient_instructions = fields.Text(string='Instructions to Patient')
    next_visit_weeks = fields.Integer(string='Next Visit In (weeks)', default=4)
    next_visit_date = fields.Date(string='Next Visit Due', compute='_compute_next_visit_date')
    session_id = fields.Many2one('dental.treatment.session', string='Treatment Session', readonly=True, copy=False,
                                 help='Session recorded on the orthodontic treatment line when the visit was completed.')

    @api.depends('chart_id.company_id')
    def _compute_company_id(self):
        self._set_company_from('chart_id')

    @api.depends('chart_id', 'date', 'visit_type')
    def _compute_name(self):
        for visit in self:
            siblings = visit.chart_id.visit_ids.filtered(lambda v: v.id and v.date and visit.date and v.date <= visit.date)
            visit.visit_number = len(siblings) or 1
            label = dict(self._fields['visit_type']._description_selection(self.env)).get(visit.visit_type, '')
            visit.name = _('Visit %(n)s - %(type)s', n=visit.visit_number, type=label.split(' (')[0])

    @api.depends('upper_wire', 'lower_wire', 'chart_id.visit_ids.upper_wire', 'chart_id.visit_ids.lower_wire',
                 'chart_id.visit_ids.state', 'date')
    def _compute_wire_changes(self):
        for visit in self:
            previous = visit._previous_done_visit()
            visit.upper_wire_changed = bool(visit.upper_wire) and visit.upper_wire != previous.upper_wire
            visit.lower_wire_changed = bool(visit.lower_wire) and visit.lower_wire != previous.lower_wire

    @api.depends('date', 'next_visit_weeks')
    def _compute_next_visit_date(self):
        for visit in self:
            visit.next_visit_date = (fields.Date.to_date(visit.date) + timedelta(weeks=visit.next_visit_weeks)
                                     if visit.date and visit.next_visit_weeks else False)

    def _previous_done_visit(self):
        self.ensure_one()
        earlier = self.chart_id.visit_ids.filtered(
            lambda v: v.state == 'done' and v.id != self._origin.id and v.date and self.date and v.date <= self.date)
        return earlier.sorted(lambda v: (v.date, v.id))[-1:]

    def _label(self, field_name):
        self.ensure_one()
        return dict(self._fields[field_name]._description_selection(self.env)).get(self[field_name], '')

    def _summary(self):
        """One line for the treatment session and the clinical timeline."""
        self.ensure_one()
        parts = [self._label('visit_type').split(' (')[0]]
        if self.upper_wire:
            parts.append(_('U: %s', self._label('upper_wire')))
        if self.lower_wire:
            parts.append(_('L: %s', self._label('lower_wire')))
        if self.elastics and self.elastics != 'none':
            parts.append(_('Elastics %(type)s %(size)s', type=self._label('elastics'), size=self.elastic_size or ''))
        if self.power_chain:
            parts.append(_('Power chain %s', self.power_chain))
        if self.aligner_tray:
            parts.append(_('Aligner %(n)s/%(total)s', n=self.aligner_tray, total=self.aligner_total or '?'))
        if self.rebond_teeth:
            parts.append(_('Re-bonded %s', self.rebond_teeth))
        if self.ipr:
            parts.append(_('IPR %s', self.ipr))
        return '; '.join(p.strip() for p in parts if p)

    def action_done(self):
        """Complete the visit: the orthodontic treatment line gets a completed session (progress, billing),
        and the next adjustment is put in Follow-ups."""
        for visit in self:
            if visit.state != 'draft':
                continue
            chart = visit.chart_id
            if chart.state in ('completed', 'cancelled'):
                raise UserError(_("%s is closed.", chart.name))
            if visit.visit_type == 'bonding' and chart.state in ('assessment', 'planned'):
                chart.action_bond(bond_date=fields.Date.to_date(visit.date))
            visit.state = 'done'
            visit._record_session()
            if visit.visit_type == 'debond' and chart.state == 'active':
                chart.action_start_retention()
            elif visit.next_visit_weeks and chart.state in ('active', 'planned', 'assessment'):
                chart._schedule_follow_up(visit.next_visit_date, _("Orthodontic adjustment (%s)", chart.name))
            chart.message_post(body=_("%(visit)s completed: %(summary)s", visit=visit.name, summary=visit._summary()))
        return True

    def _record_session(self):
        """Record a completed treatment session on the orthodontic plan line (one per adjustment visit)."""
        self.ensure_one()
        line = self.chart_id.plan_line_id
        if not line or self.session_id or line.state in ('completed', 'cancelled'):
            return
        if self.visit_type not in ('bonding', 'adjustment', 'debond'):
            return  # records, emergency and retention visits are not treatment visits of the plan
        session = self.env['dental.treatment.session'].create({
            'plan_line_id': line.id,
            'appointment_id': self.appointment_id.id or False,
            'doctor_id': self.doctor_id.id or False,
            'session_date': self.date,
            'procedure_notes': self._summary(),
        })
        session.action_complete()
        self.session_id = session
        # The orthodontic chart books its own next visit with the chosen interval
        session.follow_up_ids.filtered(lambda f: f.state == 'pending').sudo().action_cancel()

    def action_cancel(self):
        self.filtered(lambda v: v.state == 'draft').write({'state': 'cancelled'})
        return True

    def action_reset_draft(self):
        for visit in self:
            if visit.session_id:
                raise UserError(_("%s already recorded a treatment session; correct it on the session instead.", visit.name))
        self.filtered(lambda v: v.state == 'cancelled').write({'state': 'draft'})
        return True

    def action_open_visit(self):
        self.ensure_one()
        return {
            'name': self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'dental.ortho.visit',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }
