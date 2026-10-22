# -*- coding: utf-8 -*-
# pyrefly: ignore [missing-import]
from odoo import api, fields, models


class ApprovalCategory(models.Model):
    _name = 'approval.category'
    _description = 'Approval Category'
    _order = 'sequence, id'

    name = fields.Char(string='Name', required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)

    description = fields.Char(string="Description")
    create_rfq = fields.Boolean(string="Create RFQ's")
    automated_sequence = fields.Boolean(string="Automated Sequence")

    # Visual
    image = fields.Image(string='Image', max_width=256, max_height=256)
    color = fields.Integer(string='Color Index')

    # Approver configuration
    approval_minimum = fields.Integer(
        string='Minimum Approvals Required', default=1,
        help='Minimum number of approvers required before the request '
             'is fully approved.')
    approval_type = fields.Selection([
        ('sequence', 'Approvers in Sequence'),
        ('or', 'Any Approver'),
    ], string='Approval Sequence', default='or', required=True,
        help='Sequence: approvers must approve in the defined order.\n'
             'Any Approver: any single required approver can approve.')
    manager_approval = fields.Selection([
        ('required', 'Required'),
        ('optional', 'Optional'),
        ('no', 'Not Required'),
    ], string="Manager Approval", default='optional')
    is_manager_approver = fields.Boolean(string="Employee's Manager")
    user_ids = fields.One2many('approval.category.approver', 'category_id', string="Approvers")

    # Request line configuration
    has_variant = fields.Boolean(string='Has Product Variants')
    line_type = fields.Selection([
        ('none', 'None'),
        ('optional', 'Optional'),
        ('required', 'Required'),
    ], string='Product/Quantities', default='none')
    quantity = fields.Selection([
        ('none', 'None'),
        ('optional', 'Optional'),
        ('required', 'Required'),
    ], string='Quantity', default='none')
    amount = fields.Selection([
        ('none', 'None'),
        ('optional', 'Optional'),
        ('required', 'Required'),
    ], string='Amount', default='none')
    date = fields.Selection([
        ('none', 'None'),
        ('optional', 'Optional'),
        ('required', 'Required'),
    ], string='Date', default='none')
    date_start = fields.Selection([
        ('none', 'None'),
        ('optional', 'Optional'),
        ('required', 'Required'),
    ], string='Date Start', default='none')
    date_end = fields.Selection([
        ('none', 'None'),
        ('optional', 'Optional'),
        ('required', 'Required'),
    ], string='Date End', default='none')
    location = fields.Selection([
        ('none', 'None'),
        ('optional', 'Optional'),
        ('required', 'Required'),
    ], string='Location', default='none')
    reference = fields.Selection([
        ('none', 'None'),
        ('optional', 'Optional'),
        ('required', 'Required'),
    ], string='Reference', default='none')
    has_partner = fields.Selection([
        ('none', 'None'),
        ('optional', 'Optional'),
        ('required', 'Required'),
    ], string='Contact', default='none')
    payment_method = fields.Selection([
        ('none', 'None'),
        ('optional', 'Optional'),
        ('required', 'Required'),
    ], string='Payment Method', default='none')
    requirer_document = fields.Selection([
        ('none', 'None'),
        ('optional', 'Optional'),
        ('required', 'Required'),
    ], string='Supporting Document', default='none')

    request_ids = fields.One2many(
        'approval.request', 'category_id', string='Requests')
    request_to_validate_count = fields.Integer(
        compute='_compute_request_to_validate_count')
    approval_request_count = fields.Integer(
        compute='_compute_approval_request_count')
    invalid_minimum = fields.Boolean(compute='_compute_invalid_minimum')

    @api.depends('approval_minimum', 'user_ids', 'is_manager_approver')
    def _compute_invalid_minimum(self):
        for category in self:
            total_approvers = len(category.user_ids)
            if category.is_manager_approver:
                total_approvers += 1
            category.invalid_minimum = category.approval_minimum > total_approvers

    @api.onchange('create_rfq')
    def _onchange_create_rfq(self):
        if self.create_rfq:
            self.line_type = 'required'
            self.quantity = 'required'

    def _compute_request_to_validate_count(self):
        for category in self:
            category.request_to_validate_count = 0
        if not self.ids:
            return
        request_data = self.env['approval.request']._read_group([
            ('category_id', 'in', self.ids),
            ('request_status', '=', 'pending'),
            ('approver_ids.user_id', '=', self.env.user.id),
            ('approver_ids.status', '=', 'pending'),
        ], groupby=['category_id'], aggregates=['__count'])
        mapped_data = {category.id: count for category, count in request_data}
        for category in self:
            category.request_to_validate_count = mapped_data.get(category.id, 0)

    @api.depends('request_to_validate_count')
    def _compute_approval_request_count(self):
        for category in self:
            category.approval_request_count = category.request_to_validate_count

    def action_dummy(self):
        return True

    def action_view_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'approval.request',
            'view_mode': 'list,form,kanban',
            'domain': [('category_id', '=', self.id)],
            'context': {'default_category_id': self.id},
        }

    def create_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'approval.request',
            'view_mode': 'form',
            'context': {'default_category_id': self.id},
        }


    def action_edit(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'approval.category',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

class ApprovalCategoryApprover(models.Model):
    _name = 'approval.category.approver'
    _description = 'Category Approver'

    category_id = fields.Many2one('approval.category', string='Category', ondelete='cascade')
    user_id = fields.Many2one('res.users', string='User', required=True)
    required = fields.Boolean(string='Required', default=False)
