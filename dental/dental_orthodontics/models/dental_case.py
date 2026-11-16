from odoo import _, api, fields, models
from odoo.exceptions import UserError


class DentalCase(models.Model):
    _inherit = 'dental.case'

    ortho_chart_ids = fields.One2many('dental.ortho.chart', 'case_id', string='Orthodontic Charts')
    ortho_chart_count = fields.Integer(string='Orthodontic Charts', compute='_compute_ortho_chart_count')

    @api.depends('ortho_chart_ids')
    def _compute_ortho_chart_count(self):
        for case in self:
            case.ortho_chart_count = len(case.ortho_chart_ids)

    def action_open_ortho_chart(self):
        """Open this case's orthodontic chart, starting one from the case on first use."""
        self.ensure_one()
        chart = self.ortho_chart_ids.filtered(lambda c: c.state != 'cancelled')[:1]
        if not chart:
            if self.state in ('completed', 'cancelled'):
                raise UserError(_("Case %s is closed; reopen it to start an orthodontic chart.", self.name))
            Chart = self.env['dental.ortho.chart']
            Chart.check_access('create')
            plan = self.treatment_plan_ids.filtered(lambda p: p.state != 'cancelled')
            line = Chart._find_ortho_plan_line(plan.line_ids)
            chart = Chart.create({
                'patient_id': self.patient_id.id,
                'case_id': self.id,
                'doctor_id': self.doctor_id.id,
                'treatment_plan_id': line.plan_id.id or plan[:1].id or False,
                'plan_line_id': line.id or False,
                'chief_concern': self.chief_complaint,
            })
            if self.examination_ids:
                chart.action_copy_from_examination()
        return {
            'name': chart.name,
            'type': 'ir.actions.act_window',
            'res_model': 'dental.ortho.chart',
            'res_id': chart.id,
            'view_mode': 'form',
            'target': 'current',
        }
