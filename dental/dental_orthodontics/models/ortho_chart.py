from dateutil.relativedelta import relativedelta
from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# FDI permanent teeth in chart order, as seen facing the patient
UPPER_ARCH = ['18', '17', '16', '15', '14', '13', '12', '11', '21', '22', '23', '24', '25', '26', '27', '28']
LOWER_ARCH = ['48', '47', '46', '45', '44', '43', '42', '41', '31', '32', '33', '34', '35', '36', '37', '38']
CHART_ORDER = {tooth: index for index, tooth in enumerate(UPPER_ARCH + LOWER_ARCH)}

ANGLE_CLASS = [('class_1', 'Class I'), ('class_2_div1', 'Class II div 1'),
               ('class_2_div2', 'Class II div 2'), ('class_3', 'Class III')]
SIDE_RELATION = [('class_1', 'Class I'), ('class_2_quarter', '¼ Unit Class II'), ('class_2_half', '½ Unit Class II'),
                 ('class_2', 'Full Unit Class II'), ('class_3_half', '½ Unit Class III'), ('class_3', 'Full Unit Class III')]
MIDLINE = [('centered', 'Coincident'), ('right', 'Deviated Right'), ('left', 'Deviated Left')]
RETAINERS = [('none', 'None'), ('hawley', 'Hawley (removable)'), ('essix', 'Clear Vacuum-formed (Essix)'),
             ('bonded', 'Bonded / Fixed Lingual')]

# Examination molar relationship -> Angle classification
EXAM_MOLAR_TO_ANGLE = {'class_1': 'class_1', 'class_2_div1': 'class_2_div1',
                       'class_2_div2': 'class_2_div2', 'class_3': 'class_3'}


class DentalOrthoChart(models.Model):
    """Orthodontic chart: one course of orthodontic treatment of a patient.

    Workflow: assessment (records and diagnosis) -> planned (appliance and objectives agreed)
    -> active (appliances bonded; leveling, working and finishing phases with adjustment visits)
    -> retention (appliances removed, retainers fitted) -> completed.
    """
    _name = 'dental.ortho.chart'
    _description = 'Orthodontic Chart'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'dental.company.mixin']
    _order = 'id desc'

    name = fields.Char(string='Chart Number', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    patient_id = fields.Many2one('res.partner', string='Patient', required=True, index=True, tracking=True,
                                 domain=[('is_dental_patient', '=', True)])
    case_id = fields.Many2one('dental.case', string='Dental Case', index=True, tracking=True, check_company=True,
                              domain="[('patient_id', '=', patient_id)]")
    doctor_id = fields.Many2one('hr.employee.public', string='Orthodontist', tracking=True)
    treatment_plan_id = fields.Many2one('dental.treatment.plan', string='Treatment Plan', check_company=True,
                                        domain="[('patient_id', '=', patient_id)]", tracking=True)
    plan_line_id = fields.Many2one(
        'dental.treatment.plan.line', string='Orthodontic Treatment', tracking=True,
        domain="[('plan_id', '=', treatment_plan_id)]",
        help='Planned treatment (e.g. Braces) whose visits this chart records. Completing an adjustment visit '
             'records a session of it: progress, per-visit billing or installments, and the next-visit follow-up.')
    state = fields.Selection([
        ('assessment', 'Assessment'),
        ('planned', 'Planned'),
        ('active', 'Active Treatment'),
        ('retention', 'Retention'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='assessment', required=True, tracking=True, copy=False)
    phase = fields.Selection([
        ('leveling', 'Leveling & Aligning'),
        ('working', 'Working (Space Closure / Correction)'),
        ('finishing', 'Finishing & Detailing'),
    ], string='Treatment Phase', tracking=True, copy=False)

    # Live safety information
    patient_allergy_status = fields.Selection(related='patient_id.allergy_status', string='Allergy Status')
    patient_allergies = fields.Html(related='patient_id.allergies', string='Allergies')
    patient_age = fields.Integer(related='patient_id.age', string='Patient Age')
    patient_gender = fields.Selection(related='patient_id.gender', string='Patient Gender')
    patient_image = fields.Image(related='patient_id.image_128', string='Patient Photo')

    # ------------------------------------------------------------------
    # Orthodontic assessment
    # ------------------------------------------------------------------
    chief_concern = fields.Text(string="Patient's Concern", help='What the patient wants corrected, in their words.')
    angle_class = fields.Selection(ANGLE_CLASS, string='Angle Classification', tracking=True)
    molar_right = fields.Selection(SIDE_RELATION, string='Molar Right')
    molar_left = fields.Selection(SIDE_RELATION, string='Molar Left')
    canine_right = fields.Selection(SIDE_RELATION, string='Canine Right')
    canine_left = fields.Selection(SIDE_RELATION, string='Canine Left')
    overjet = fields.Float(string='Overjet (mm)', digits=(4, 1))
    overbite = fields.Float(string='Overbite (mm)', digits=(4, 1), help='Negative values record an open bite.')
    overbite_percent = fields.Integer(string='Overbite (%)', help='Vertical overlap of the lower incisors, in percent.')
    open_bite = fields.Boolean(string='Open Bite')
    crossbite = fields.Selection([('none', 'None'), ('anterior', 'Anterior'), ('posterior_right', 'Posterior Right'),
                                  ('posterior_left', 'Posterior Left'), ('posterior_bilateral', 'Posterior Bilateral'),
                                  ('scissor', 'Scissor Bite')], string='Crossbite', default='none')
    crossbite_teeth = fields.Char(string='Teeth in Crossbite', help='FDI numbers, e.g. 12, 22')
    upper_midline = fields.Selection(MIDLINE, string='Upper Midline (to face)')
    upper_midline_mm = fields.Float(string='Upper Midline Shift (mm)', digits=(3, 1))
    lower_midline = fields.Selection(MIDLINE, string='Lower Midline (to upper)')
    lower_midline_mm = fields.Float(string='Lower Midline Shift (mm)', digits=(3, 1))
    crowding_upper = fields.Float(string='Upper Arch Crowding (mm)', digits=(4, 1),
                                  help='Space discrepancy: positive = crowding, negative = spacing.')
    crowding_lower = fields.Float(string='Lower Arch Crowding (mm)', digits=(4, 1),
                                  help='Space discrepancy: positive = crowding, negative = spacing.')
    curve_of_spee = fields.Selection([('flat', 'Flat'), ('mild', 'Mild'), ('moderate', 'Moderate'), ('deep', 'Deep')],
                                     string='Curve of Spee')
    skeletal_pattern = fields.Selection([('class_1', 'Skeletal Class I'), ('class_2', 'Skeletal Class II'),
                                         ('class_3', 'Skeletal Class III')], string='Skeletal Pattern')
    vertical_pattern = fields.Selection([('normal', 'Normodivergent'), ('low', 'Hypodivergent (Low Angle)'),
                                         ('high', 'Hyperdivergent (High Angle)')], string='Vertical Pattern')
    profile = fields.Selection([('straight', 'Straight'), ('convex', 'Convex'), ('concave', 'Concave')], string='Profile')
    habits = fields.Char(string='Habits', help='e.g. Thumb sucking, tongue thrust, mouth breathing')
    tmj_notes = fields.Char(string='TMJ')
    iotn_dhc = fields.Selection([('1', '1 - None'), ('2', '2 - Little'), ('3', '3 - Borderline'),
                                 ('4', '4 - Great'), ('5', '5 - Very Great')],
                                string='IOTN Dental Health Component', tracking=True,
                                help='Index of Orthodontic Treatment Need, Dental Health Component (grade 1 to 5).')
    iotn_ac = fields.Selection([(str(i), str(i)) for i in range(1, 11)], string='IOTN Aesthetic Component',
                               help='Aesthetic Component (1 = most attractive, 10 = least).')
    treatment_need = fields.Selection([('none', 'No Need'), ('borderline', 'Borderline Need'), ('need', 'Definite Need')],
                                      string='Treatment Need', compute='_compute_treatment_need', store=True)
    # Cephalometric analysis (Steiner / Tweed values most used in practice)
    ceph_sna = fields.Float(string='SNA (°)', digits=(4, 1), help='Norm 82° ± 2')
    ceph_snb = fields.Float(string='SNB (°)', digits=(4, 1), help='Norm 80° ± 2')
    ceph_anb = fields.Float(string='ANB (°)', digits=(4, 1), compute='_compute_ceph_anb', store=True,
                            help='SNA - SNB. Norm 2° ± 2: above 4° suggests skeletal Class II, below 0° Class III.')
    ceph_fma = fields.Float(string='FMA (°)', digits=(4, 1), help='Frankfort-mandibular plane angle. Norm 25° ± 5')
    ceph_impa = fields.Float(string='IMPA (°)', digits=(4, 1), help='Lower incisor to mandibular plane. Norm 90° ± 5')
    ceph_u1_sn = fields.Float(string='U1-SN (°)', digits=(4, 1), help='Upper incisor to SN. Norm 103° ± 6')
    ceph_notes = fields.Text(string='Cephalometric Notes')
    diagnosis_summary = fields.Text(string='Orthodontic Diagnosis')

    # ------------------------------------------------------------------
    # Treatment plan
    # ------------------------------------------------------------------
    appliance_type = fields.Selection([
        ('fixed_metal', 'Fixed - Metal Brackets'),
        ('fixed_ceramic', 'Fixed - Ceramic Brackets'),
        ('self_ligating', 'Fixed - Self-ligating'),
        ('lingual', 'Fixed - Lingual'),
        ('aligners', 'Clear Aligners'),
        ('removable', 'Removable Appliance'),
        ('functional', 'Functional Appliance'),
    ], string='Appliance', tracking=True)
    bracket_prescription = fields.Selection([('mbt', 'MBT'), ('roth', 'Roth'), ('standard', 'Standard Edgewise'),
                                             ('damon', 'Damon'), ('other', 'Other')], string='Bracket Prescription')
    slot_size = fields.Selection([('018', '0.018"'), ('022', '0.022"')], string='Slot Size')
    arches = fields.Selection([('both', 'Upper & Lower'), ('upper', 'Upper Only'), ('lower', 'Lower Only')],
                              string='Arches Treated', default='both', required=True)
    extraction_plan = fields.Selection([
        ('none', 'Non-extraction'),
        ('u4', 'Upper First Premolars'),
        ('u4_l4', 'Upper & Lower First Premolars'),
        ('u4_l5', 'Upper First & Lower Second Premolars'),
        ('u5_l5', 'Upper & Lower Second Premolars'),
        ('other', 'Other'),
    ], string='Extractions', default='none')
    extraction_teeth = fields.Char(string='Teeth to Extract', help='FDI numbers, e.g. 14, 24, 34, 44')
    anchorage = fields.Selection([('minimum', 'Minimum'), ('moderate', 'Moderate'), ('maximum', 'Maximum'),
                                  ('tads', 'Absolute (TADs / Mini-screws)')], string='Anchorage')
    auxiliaries = fields.Char(string='Auxiliaries', help='e.g. Rapid palatal expander, TPA, Nance, headgear, mini-screws')
    treatment_objectives = fields.Text(string='Treatment Objectives')
    estimated_months = fields.Integer(string='Estimated Duration (months)', default=18)
    visit_interval_weeks = fields.Integer(string='Adjustment Every (weeks)', default=4,
                                          help='Default interval between adjustment visits.')
    consent_given = fields.Boolean(string='Informed Consent Signed', tracking=True)

    start_date = fields.Date(string='Bonding Date', tracking=True, copy=False)
    estimated_end_date = fields.Date(string='Estimated Debond', compute='_compute_dates', store=True)
    debond_date = fields.Date(string='Debond Date', tracking=True, copy=False)
    months_in_treatment = fields.Integer(string='Months in Treatment', compute='_compute_dates')

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------
    retainer_upper = fields.Selection(RETAINERS, string='Upper Retainer')
    retainer_lower = fields.Selection(RETAINERS, string='Lower Retainer')
    retention_wear = fields.Selection([('fulltime', 'Full-time'), ('nights', 'Nights Only'),
                                       ('alternate', 'Alternate Nights'), ('lifetime', 'Nights, Lifelong')],
                                      string='Retainer Wear')
    retention_review_months = fields.Integer(string='Retention Review Every (months)', default=6)
    retention_notes = fields.Text(string='Retention Instructions')

    # ------------------------------------------------------------------
    # Chart and visits
    # ------------------------------------------------------------------
    tooth_ids = fields.One2many('dental.ortho.tooth', 'chart_id', string='Bracket Chart', copy=False)
    visit_ids = fields.One2many('dental.ortho.visit', 'chart_id', string='Visits', copy=False)
    visit_count = fields.Integer(string='Visits Done', compute='_compute_visit_stats')
    planned_visits = fields.Integer(string='Planned Visits', related='plan_line_id.number_of_visits')
    progress = fields.Float(string='Progress', compute='_compute_visit_stats')
    last_visit_date = fields.Datetime(string='Last Visit', compute='_compute_visit_stats')
    current_upper_wire = fields.Char(string='Current Upper Wire', compute='_compute_visit_stats')
    current_lower_wire = fields.Char(string='Current Lower Wire', compute='_compute_visit_stats')
    current_elastics = fields.Char(string='Current Elastics', compute='_compute_visit_stats')
    bonded_count = fields.Integer(string='Appliances Bonded', compute='_compute_tooth_stats')
    failed_count = fields.Integer(string='Loose / Failed', compute='_compute_tooth_stats')
    chart_html = fields.Html(string='Chart', compute='_compute_chart_html', sanitize=False)

    @api.depends('case_id.company_id')
    def _compute_company_id(self):
        self._set_company_from('case_id')

    @api.depends('iotn_dhc')
    def _compute_treatment_need(self):
        for chart in self:
            dhc = chart.iotn_dhc
            chart.treatment_need = (dhc in ('4', '5') and 'need') or (dhc == '3' and 'borderline') or (dhc and 'none') or False

    @api.depends('ceph_sna', 'ceph_snb')
    def _compute_ceph_anb(self):
        for chart in self:
            chart.ceph_anb = (chart.ceph_sna - chart.ceph_snb) if chart.ceph_sna and chart.ceph_snb else 0.0

    @api.depends('start_date', 'estimated_months', 'debond_date')
    def _compute_dates(self):
        today = fields.Date.context_today(self)
        for chart in self:
            chart.estimated_end_date = (chart.start_date + relativedelta(months=chart.estimated_months)
                                        if chart.start_date and chart.estimated_months else False)
            end = chart.debond_date or today
            if chart.start_date and end >= chart.start_date:
                delta = relativedelta(end, chart.start_date)
                chart.months_in_treatment = delta.years * 12 + delta.months
            else:
                chart.months_in_treatment = 0

    @api.depends('visit_ids.state', 'visit_ids.date', 'visit_ids.upper_wire', 'visit_ids.lower_wire',
                 'visit_ids.elastics', 'plan_line_id.number_of_visits')
    def _compute_visit_stats(self):
        for chart in self:
            done = chart.visit_ids.filtered(lambda v: v.state == 'done').sorted(lambda v: (v.date, v.id))
            chart.visit_count = len(done)
            chart.last_visit_date = done[-1:].date
            upper = done.filtered('upper_wire')[-1:]
            lower = done.filtered('lower_wire')[-1:]
            chart.current_upper_wire = upper._label('upper_wire') if upper else False
            chart.current_lower_wire = lower._label('lower_wire') if lower else False
            last = done[-1:]
            chart.current_elastics = (last._label('elastics') if last and last.elastics not in (False, 'none') else False)
            planned = chart.plan_line_id.number_of_visits
            chart.progress = min(100.0, 100.0 * len(done) / planned) if planned else 0.0

    @api.depends('tooth_ids.status')
    def _compute_tooth_stats(self):
        for chart in self:
            chart.bonded_count = len(chart.tooth_ids.filtered(lambda t: t.status == 'bonded'))
            chart.failed_count = len(chart.tooth_ids.filtered(lambda t: t.status == 'failed'))

    @api.depends('tooth_ids.status', 'tooth_ids.appliance', 'tooth_ids.tooth_number', 'tooth_ids.missing',
                 'visit_ids.state', 'visit_ids.upper_wire', 'visit_ids.lower_wire')
    def _compute_chart_html(self):
        for chart in self:
            chart.chart_html = chart._render_chart()

    # ------------------------------------------------------------------
    # Bracket chart drawing
    # ------------------------------------------------------------------
    def _render_chart(self):
        """Both arches as tooth cells (FDI), coloured by appliance status, with the wires in place."""
        self.ensure_one()
        teeth = {t.tooth_number: t for t in self.tooth_ids}
        appliance_short = {'bracket': 'BR', 'tube': 'TB', 'band': 'BD', 'attachment': 'AT', 'button': 'BT'}

        def cell(number):
            tooth = teeth.get(number)
            if not tooth:
                return Markup('<div class="o_ortho_tooth is-none"><span class="o_ortho_num">%s</span></div>') % number
            status = 'missing' if tooth.missing else (tooth.status or 'none')
            label = '' if tooth.missing else appliance_short.get(tooth.appliance, '')
            title = '%s: %s' % (tooth.tooth_number, tooth._status_label())
            return Markup(
                '<div class="o_ortho_tooth is-%s" title="%s"><span class="o_ortho_num">%s</span>'
                '<span class="o_ortho_app">%s</span></div>') % (status, title, number, label or ' ')

        def arch(numbers, wire, label):
            left, right = numbers[:8], numbers[8:]
            return Markup(
                '<div class="o_ortho_arch"><div class="o_ortho_arch_label">%s<small>%s</small></div>'
                '<div class="o_ortho_row"><div class="o_ortho_half">%s</div><div class="o_ortho_mid"></div>'
                '<div class="o_ortho_half">%s</div></div></div>') % (
                label, wire or _('No wire'), Markup('').join(cell(n) for n in left), Markup('').join(cell(n) for n in right))

        legend = Markup('').join(
            Markup('<span class="o_ortho_key is-%s"><i></i>%s</span>') % (key, escape(text))
            for key, text in [('planned', _('Planned')), ('bonded', _('Bonded')), ('failed', _('Loose / Failed')),
                              ('debonded', _('Removed')), ('missing', _('Missing / Extracted')),
                              ('none', _('No Appliance'))])
        return Markup(
            '<div class="o_ortho_chart">%s%s<div class="o_ortho_legend">%s'
            '<span class="o_ortho_abbr">BR bracket · TB tube · BD band · AT attachment · BT button</span></div></div>') % (
            arch(UPPER_ARCH, self.current_upper_wire, _('Upper')),
            arch(LOWER_ARCH, self.current_lower_wire, _('Lower')),
            legend)

    def _default_tooth_vals(self):
        """Standard full-arch setup: brackets 5-5, tubes on first and second molars, nothing on third molars."""
        self.ensure_one()
        vals = []
        arches = UPPER_ARCH * (self.arches in ('both', 'upper')) + LOWER_ARCH * (self.arches in ('both', 'lower'))
        is_aligner = self.appliance_type == 'aligners'
        for number in arches:
            position = int(number[1])
            if position == 8:
                appliance, status = 'none', 'none'
            elif is_aligner:
                appliance, status = 'none', 'none'
            elif position in (6, 7):
                appliance, status = 'tube', 'planned'
            else:
                appliance, status = 'bracket', 'planned'
            vals.append({'chart_id': self.id, 'tooth_number': number, 'appliance': appliance, 'status': status})
        return vals

    def _ensure_teeth(self):
        Tooth = self.env['dental.ortho.tooth']
        for chart in self.filtered(lambda c: not c.tooth_ids):
            Tooth.create(chart._default_tooth_vals())

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('dental.ortho.chart') or _('New')
        charts = super().create(vals_list)
        charts._ensure_teeth()
        return charts

    @api.onchange('case_id')
    def _onchange_case_id(self):
        case = self.case_id
        if case:
            self.patient_id = case.patient_id
            self.doctor_id = self.doctor_id or case.doctor_id
            if not self.treatment_plan_id:
                self.treatment_plan_id = case.treatment_plan_ids.filtered(lambda p: p.state != 'cancelled')[:1]

    @api.onchange('treatment_plan_id')
    def _onchange_treatment_plan_id(self):
        if self.plan_line_id and self.plan_line_id.plan_id != self.treatment_plan_id:
            self.plan_line_id = False
        if self.treatment_plan_id and not self.plan_line_id:
            self.plan_line_id = self._find_ortho_plan_line(self.treatment_plan_id.line_ids)

    @api.model
    def _find_ortho_plan_line(self, lines):
        """The orthodontic line of a plan: an Orthodontics treatment, otherwise the multi-visit one."""
        lines = lines.filtered(lambda l: l.state != 'cancelled' and l.acceptance != 'declined')
        ortho = lines.filtered(lambda l: (l.treatment_id.dental_treatment_category_id.name or '').lower().startswith('orthodon'))
        return (ortho or lines.filtered(lambda l: l.number_of_visits > 1))[:1]

    @api.constrains('overjet', 'overbite', 'crowding_upper', 'crowding_lower', 'estimated_months')
    def _check_measurements(self):
        for chart in self:
            if abs(chart.overjet) > 25 or abs(chart.overbite) > 25:
                raise ValidationError(_("Overjet and overbite must be within ±25 mm."))
            if abs(chart.crowding_upper) > 30 or abs(chart.crowding_lower) > 30:
                raise ValidationError(_("Crowding / spacing must be within ±30 mm per arch."))
            if chart.estimated_months < 0 or chart.estimated_months > 120:
                raise ValidationError(_("The estimated duration must be between 0 and 120 months."))

    @api.constrains('plan_line_id', 'patient_id')
    def _check_plan_line_patient(self):
        for chart in self:
            if chart.plan_line_id and chart.plan_line_id.plan_id.patient_id != chart.patient_id:
                raise ValidationError(_("The orthodontic treatment line must belong to the same patient."))

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_confirm_plan(self):
        for chart in self:
            if not chart.appliance_type:
                raise UserError(_("Choose the appliance before confirming the orthodontic plan of %s.", chart.name))
            chart.state = 'planned'
            chart.message_post(body=_("Orthodontic treatment plan confirmed."))
        return True

    def action_bond(self, bond_date=None):
        """Appliances fitted: planned brackets and tubes become bonded and active treatment starts."""
        today = bond_date or fields.Date.context_today(self)
        for chart in self:
            if chart.state not in ('assessment', 'planned'):
                raise UserError(_("%s is already in treatment.", chart.name))
            if not chart.appliance_type:
                raise UserError(_("Choose the appliance before bonding (%s).", chart.name))
            chart._ensure_teeth()
            chart.tooth_ids.filtered(lambda t: t.status == 'planned' and not t.missing).write(
                {'status': 'bonded', 'bonded_date': today})
            chart.write({'state': 'active', 'phase': 'leveling', 'start_date': chart.start_date or today})
            chart.message_post(body=_("Appliances bonded: active orthodontic treatment started."))
        return True

    def action_start_retention(self):
        """Debond: appliances removed and retainers fitted."""
        today = fields.Date.context_today(self)
        for chart in self:
            if chart.state != 'active':
                raise UserError(_("Only charts in active treatment can move to retention (%s).", chart.name))
            chart.tooth_ids.filtered(lambda t: t.status in ('bonded', 'failed')).write(
                {'status': 'debonded', 'debonded_date': today})
            chart.write({'state': 'retention', 'debond_date': chart.debond_date or today, 'phase': False})
            chart.message_post(body=_("Appliances removed (debond). Retention phase started."))
            chart._schedule_follow_up(today + relativedelta(months=max(chart.retention_review_months, 1)),
                                      _("Retention review (%s)", chart.name), 'review')
        return True

    def action_complete(self):
        self.write({'state': 'completed'})
        for chart in self:
            chart.message_post(body=_("Orthodontic treatment completed."))
        return True

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        return True

    def action_reset_to_assessment(self):
        self.filtered(lambda c: c.state == 'cancelled').write({'state': 'assessment'})
        return True

    def action_reset_chart(self):
        """Rebuild the bracket chart from the plan (only before bonding)."""
        for chart in self:
            if chart.state not in ('assessment', 'planned'):
                raise UserError(_("The bracket chart can only be rebuilt before bonding."))
            chart.tooth_ids.unlink()
        self._ensure_teeth()
        return True

    def action_copy_from_examination(self):
        """Take the occlusion recorded in the case's examination as the starting point of the assessment."""
        for chart in self:
            exam = chart.case_id.examination_ids.sorted(lambda e: (e.examination_date, e.id), reverse=True)[:1]
            if not exam:
                raise UserError(_("Case %s has no examination yet.", chart.case_id.display_name or '-'))
            vals = {}
            if exam.molar_relation and not chart.angle_class:
                vals['angle_class'] = EXAM_MOLAR_TO_ANGLE.get(exam.molar_relation)
            for field in ('overjet', 'overbite'):
                if exam[field] and not chart[field]:
                    vals[field] = exam[field]
            if exam.open_bite and not chart.open_bite:
                vals['open_bite'] = True
            if exam.crossbite and exam.crossbite != 'none' and chart.crossbite in (False, 'none'):
                vals['crossbite'] = {'anterior': 'anterior', 'posterior': 'posterior_bilateral',
                                     'both': 'posterior_bilateral'}.get(exam.crossbite, 'none')
            if exam.eo_facial_profile and not chart.profile:
                vals['profile'] = exam.eo_facial_profile
            if not chart.chief_concern and exam.chief_complaint:
                vals['chief_concern'] = exam.chief_complaint
            chart.write(vals)
        return True

    def action_new_visit(self):
        """Start today's adjustment visit, carrying the current wires and elastics forward."""
        self.ensure_one()
        if self.state in ('completed', 'cancelled'):
            raise UserError(_("%s is closed.", self.name))
        visit = self.env['dental.ortho.visit'].create(self._prepare_next_visit_vals())
        return visit.action_open_visit()

    def _prepare_next_visit_vals(self):
        self.ensure_one()
        last = self.visit_ids.filtered(lambda v: v.state == 'done').sorted(lambda v: (v.date, v.id))[-1:]
        case = self.case_id
        visit = case.current_visit_id if case else False
        if self.state in ('assessment', 'planned'):
            visit_type = 'bonding'
        elif self.state == 'retention':
            visit_type = 'retention_check'
        else:
            visit_type = 'adjustment'
        return {
            'chart_id': self.id,
            'appointment_id': visit.id if visit else False,
            'doctor_id': (visit.doctor_id.id if visit and visit.doctor_id else self.doctor_id.id),
            'visit_type': visit_type,
            'upper_wire': last.upper_wire,
            'lower_wire': last.lower_wire,
            'elastics': last.elastics or 'none',
            'elastic_size': last.elastic_size,
            'elastic_wear': last.elastic_wear,
            'aligner_tray': (last.aligner_tray + 1) if last.aligner_tray else 0,
            'aligner_total': last.aligner_total,
            'next_visit_weeks': last.next_visit_weeks or self.visit_interval_weeks or 4,
        }

    def _schedule_follow_up(self, date, reason, follow_up_type='next_visit'):
        """Next appointment to book, shown in Follow-ups and on the case."""
        self.ensure_one()
        FollowUp = self.env['dental.follow.up'].sudo()
        pending = FollowUp.search([('patient_id', '=', self.patient_id.id), ('state', '=', 'pending'),
                                   ('case_id', '=', self.case_id.id), ('date', '>=', fields.Date.context_today(self))])
        if pending:
            pending[:1].write({'date': date, 'reason': reason})
            return pending[:1]
        return FollowUp.create({
            'patient_id': self.patient_id.id,
            'case_id': self.case_id.id or False,
            'doctor_id': self.doctor_id.id or False,
            'follow_up_type': follow_up_type,
            'treatment_id': self.plan_line_id.treatment_id.id or False,
            'date': date,
            'reason': reason,
            'priority': '1',
        })

    def action_open_visits(self):
        self.ensure_one()
        return {
            'name': _('Orthodontic Visits'),
            'type': 'ir.actions.act_window',
            'res_model': 'dental.ortho.visit',
            'view_mode': 'list,form',
            'domain': [('chart_id', '=', self.id)],
            'context': {'default_chart_id': self.id},
        }

    def action_open_case(self):
        self.ensure_one()
        return {
            'name': self.case_id.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'dental.case',
            'res_id': self.case_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
