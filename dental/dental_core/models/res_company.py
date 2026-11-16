from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    dental_consultation_product_id = fields.Many2one(
        'product.product',
        string='Consultation Fee Service',
        domain=[('type', '=', 'service')],
        help='Service used on patient invoices for the consultation fee. '
             'Defaults to the catalog "Consultation" service when empty.'
    )
    dental_auto_invoice = fields.Boolean(
        string='Draft Invoice on Consultation Completion',
        default=True,
        help='Automatically prepare a draft patient invoice when the doctor completes a consultation.'
    )


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    dental_consultation_product_id = fields.Many2one(
        related='company_id.dental_consultation_product_id', readonly=False)
    dental_auto_invoice = fields.Boolean(
        related='company_id.dental_auto_invoice', readonly=False)


class ResCompanyFloorPlan(models.Model):
    _inherit = 'res.company'

    dental_chair_count = fields.Integer(
        string='Dental Chairs', default=4,
        help='Number of dental chairs in this clinic, used for chair occupancy on the dashboard.')
    dental_floor_plan_image = fields.Binary(
        string='Floor Plan Background', attachment=True,
        help='Optional image (e.g. the clinic layout drawing) shown behind the rooms on the dashboard floor plan.')
