# -*- coding: utf-8 -*-
from odoo import models, fields, api

class MrpEcoApproval(models.Model):
    _name = 'mrp.eco.approval'
    _description = 'ECO Approval'
    
    eco_id = fields.Many2one('mrp.eco', string='ECO', required=True, ondelete='cascade')
    approval_template_id = fields.Many2one('mrp.eco.approval.template', string='Template', required=True)
    name = fields.Char(related='approval_template_id.name', string='Role', store=True)
    user_id = fields.Many2one('res.users', string='Approved by')
    status = fields.Selection([
        ('none', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], string='Status', default='none', required=True)
    is_approved = fields.Boolean('Is Approved', compute='_compute_is_approved', store=True)
    
    @api.depends('status')
    def _compute_is_approved(self):
        for record in self:
            record.is_approved = record.status == 'approved'
            
    def action_approve(self):
        self.ensure_one()
        self.write({
            'status': 'approved',
            'user_id': self.env.user.id
        })

    def action_reject(self):
        self.ensure_one()
        self.write({
            'status': 'rejected',
            'user_id': self.env.user.id
        })
