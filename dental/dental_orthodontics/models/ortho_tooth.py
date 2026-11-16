from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .ortho_chart import CHART_ORDER


class DentalOrthoTooth(models.Model):
    """One tooth of the bracket chart: the appliance on it and its bond history."""
    _name = 'dental.ortho.tooth'
    _description = 'Orthodontic Bracket Chart Entry'
    _inherit = ['dental.company.mixin']
    _order = 'chart_id, sequence'

    chart_id = fields.Many2one('dental.ortho.chart', string='Orthodontic Chart', required=True, index=True,
                               ondelete='cascade', check_company=True)
    patient_id = fields.Many2one(related='chart_id.patient_id', store=True, index=True, string='Patient')
    tooth_number = fields.Char(string='Tooth (FDI)', required=True)
    sequence = fields.Integer(string='Chart Position', compute='_compute_position', store=True)
    arch = fields.Selection([('upper', 'Upper'), ('lower', 'Lower')], string='Arch', compute='_compute_position', store=True)
    appliance = fields.Selection([
        ('none', 'None'),
        ('bracket', 'Bracket'),
        ('tube', 'Buccal Tube'),
        ('band', 'Band'),
        ('attachment', 'Aligner Attachment'),
        ('button', 'Button / Cleat'),
    ], string='Appliance', default='bracket', required=True)
    status = fields.Selection([
        ('none', 'Not Included'),
        ('planned', 'Planned'),
        ('bonded', 'Bonded'),
        ('failed', 'Loose / Failed'),
        ('debonded', 'Removed'),
    ], string='Status', default='planned', required=True)
    missing = fields.Boolean(string='Missing / Extracted')
    bonded_date = fields.Date(string='Bonded On')
    debonded_date = fields.Date(string='Removed On')
    rebond_count = fields.Integer(string='Re-bonds', readonly=True)
    note = fields.Char(string='Notes', help='e.g. Bracket repositioned, rotated 15°')

    _tooth_uniq = models.Constraint('unique(chart_id, tooth_number)', 'Each tooth appears once in the bracket chart.')

    @api.depends('chart_id.company_id')
    def _compute_company_id(self):
        self._set_company_from('chart_id')

    @api.depends('tooth_number')
    def _compute_position(self):
        for tooth in self:
            number = (tooth.tooth_number or '').strip()
            tooth.sequence = CHART_ORDER.get(number, 99)
            tooth.arch = 'upper' if number[:1] in ('1', '2') else ('lower' if number[:1] in ('3', '4') else False)

    @api.constrains('tooth_number')
    def _check_tooth_number(self):
        for tooth in self:
            if (tooth.tooth_number or '').strip() not in CHART_ORDER:
                raise ValidationError(_("Invalid tooth %s: use FDI numbers of permanent teeth (11-48).", tooth.tooth_number))

    def _status_label(self):
        self.ensure_one()
        if self.missing:
            return _('Missing / Extracted')
        status = dict(self._fields['status']._description_selection(self.env)).get(self.status, '')
        appliance = dict(self._fields['appliance']._description_selection(self.env)).get(self.appliance, '')
        return '%s %s' % (appliance, status.lower()) if self.appliance != 'none' else status

    @api.onchange('appliance')
    def _onchange_appliance(self):
        if self.appliance == 'none':
            self.status = 'none'
        elif self.status == 'none':
            self.status = 'planned'

    def action_bond(self):
        today = fields.Date.context_today(self)
        for tooth in self:
            vals = {'status': 'bonded', 'bonded_date': today}
            if tooth.status == 'failed':
                vals['rebond_count'] = tooth.rebond_count + 1
            if tooth.appliance == 'none':
                vals['appliance'] = 'bracket'
            tooth.write(vals)
            tooth.chart_id.message_post(body=_("Tooth %(tooth)s: %(what)s.", tooth=tooth.tooth_number,
                                               what=_('re-bonded') if 'rebond_count' in vals else _('bonded')))
        return True

    def action_mark_failed(self):
        self.filtered(lambda t: t.status == 'bonded').write({'status': 'failed'})
        for tooth in self:
            tooth.chart_id.message_post(body=_("Tooth %s: appliance loose / failed.", tooth.tooth_number))
        return True

    def action_remove(self):
        self.write({'status': 'debonded', 'debonded_date': fields.Date.context_today(self)})
        return True
