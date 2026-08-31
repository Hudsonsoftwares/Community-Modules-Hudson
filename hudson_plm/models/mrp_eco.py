# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class MrpEco(models.Model):
    _name = 'mrp.eco'
    _description = 'Engineering Change Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char('Reference', required=True, copy=False, default=lambda self: _('New'))
    type_id = fields.Many2one('mrp.eco.type', string='Type', required=True)
    type = fields.Selection([
        ('bom', 'Bill of Materials'),
        ('routing', 'Routing'),
        ('product', 'Product Only')
    ], string='Apply on', default='bom', required=True)

    stage_id = fields.Many2one('mrp.eco.stage', string='Stage', copy=False, group_expand='_read_group_stage_ids', tracking=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    product_tmpl_id = fields.Many2one('product.template', string='Product', required=True)
    bom_id = fields.Many2one('mrp.bom', string='Bill of Materials', domain="[('product_tmpl_id', '=', product_tmpl_id)]")
    new_bom_id = fields.Many2one('mrp.bom', string='New Bill of Materials', copy=False)

    user_id = fields.Many2one('res.users', string='Responsible', default=lambda self: self.env.user, tracking=True)
    effectivity = fields.Selection([
        ('asap', 'As soon as possible'),
        ('date', 'At Date')
    ], string='Effective Date', default='asap', required=True)
    effectivity_date = fields.Datetime('Effective Date (Custom)', tracking=True)

    tag_ids = fields.Many2many('mrp.eco.tag', string='Tags')
    note = fields.Html('Note')

    update_version = fields.Boolean('Update Version', default=True)
    new_bom_version = fields.Integer('New BoM Version', related='new_bom_id.version')
    document_count = fields.Integer('Document Count', compute='_compute_document_count')

    # Track if changes have been applied so Apply Changes button disappears after use
    is_applied = fields.Boolean('Changes Applied', default=False, copy=False, tracking=True)

    approval_ids = fields.One2many('mrp.eco.approval', 'eco_id', string='Approvals')
    color = fields.Integer('Color')

    user_can_approve = fields.Boolean(
        'Can Approve', compute='_compute_user_can_approve')
    user_can_reject = fields.Boolean(
        'Can Reject', compute='_compute_user_can_approve')

    state = fields.Selection([
        ('progress', 'In Progress'),
        ('done', 'Done'),
        ('conflict', 'Conflict')
    ], string='Status', compute='_compute_state', store=True)

    def _compute_document_count(self):
        for eco in self:
            eco.document_count = self.env['ir.attachment'].search_count([
                ('res_model', '=', 'mrp.eco'),
                ('res_id', '=', eco.id)
            ])

    @api.depends('stage_id', 'stage_id.final_stage', 'approval_ids.status')
    def _compute_state(self):
        for eco in self:
            if eco.stage_id.final_stage:
                eco.state = 'done'
            elif any(a.status == 'rejected' for a in eco.approval_ids):
                eco.state = 'conflict'
            else:
                eco.state = 'progress'

    def _compute_user_can_approve(self):
        for eco in self:
            can_approve = False
            can_reject = False
            for approval in eco.approval_ids.filtered(lambda a: a.status == 'none'):
                if self.env.user in approval.approval_template_id.user_ids:
                    can_approve = True
                    can_reject = True
                    break
            eco.user_can_approve = can_approve
            eco.user_can_reject = can_reject

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('mrp.eco') or _('New')
            if not vals.get('stage_id'):
                type_id = vals.get('type_id')
                if type_id:
                    stage = self.env['mrp.eco.stage'].search([('type_ids', 'in', type_id)], order='sequence', limit=1)
                    if stage:
                        vals['stage_id'] = stage.id
        ecos = super(MrpEco, self).create(vals_list)
        ecos._create_approvals()
        return ecos

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return stages.search([], order='sequence')

    def write(self, vals):
        # Before changing stage, enforce mandatory approvals on CURRENT stage
        if 'stage_id' in vals:
            for eco in self:
                if eco.stage_id:
                    current_stage_templates = eco.stage_id.approval_template_ids.filtered(
                        lambda t: t.approval_type == 'mandatory'
                    )
                    if current_stage_templates:
                        pending_approvals = eco.approval_ids.filtered(
                            lambda a: a.approval_template_id in current_stage_templates
                            and a.status != 'approved'
                        )
                        if pending_approvals:
                            roles = ', '.join(pending_approvals.mapped('name'))
                            raise UserError(_(
                                'Cannot move to the next stage. Mandatory approvals for stage '
                                '"%s" are still pending: %s'
                            ) % (eco.stage_id.name, roles))

        res = super(MrpEco, self).write(vals)

        if 'stage_id' in vals:
            # Create approval records for the newly entered stage
            self._create_approvals()
            # If the new stage has allow_apply_change, auto-apply
            for eco in self:
                if eco.stage_id.allow_apply_change and not eco.is_applied:
                    eco.action_apply_changes()

        return res

    def _create_approvals(self):
        for eco in self:
            if eco.stage_id and eco.stage_id.approval_template_ids:
                existing_templates = eco.approval_ids.mapped('approval_template_id')
                new_templates = eco.stage_id.approval_template_ids - existing_templates
                for template in new_templates:
                    self.env['mrp.eco.approval'].create({
                        'eco_id': eco.id,
                        'approval_template_id': template.id,
                    })

    def action_start_revision(self):
        for eco in self:
            if not eco.bom_id:
                raise UserError(_('Please select a Bill of Materials before starting a revision.'))
            if eco.new_bom_id:
                raise UserError(_('A revision has already been started for this ECO.'))
            if eco.type == 'bom':
                new_version = eco.bom_id.version + 1 if eco.update_version else eco.bom_id.version
                eco.new_bom_id = eco.bom_id.copy({
                    'version': new_version,
                    'active': False,
                })
                eco.message_post(body=_(
                    'Revision started. A new draft BoM (V%s) has been created and is ready for editing.'
                ) % new_version)

    def action_apply_changes(self):
        for eco in self:
            if not eco.new_bom_id:
                raise UserError(_('Please click "Start Revision" first to create a draft BoM before applying changes.'))
            if eco.is_applied:
                raise UserError(_('Changes have already been applied to this ECO.'))
            if eco.type == 'bom':
                # Archive old BoM, activate the new revised BoM
                if eco.bom_id:
                    eco.bom_id.with_context(active_test=False).write({'active': False})
                eco.new_bom_id.with_context(active_test=False).write({'active': True})
                eco.write({'is_applied': True})
                eco.message_post(body=_(
                    'Changes applied successfully. The BoM has been updated to version V%s. '
                    'The previous version has been archived.'
                ) % eco.new_bom_id.version)

    def action_review_changes(self):
        self.ensure_one()
        if not self.new_bom_id:
            raise UserError(_('Please start a revision first before reviewing changes.'))
        if not self.bom_id:
            raise UserError(_('No original Bill of Materials to compare against.'))

        # Clear previous comparison records
        self.env['mrp.eco.bom.change'].search([('eco_id', '=', self.id)]).unlink()

        # Read BoM lines with active_test=False to access archived draft BoM
        old_lines = {
            line.product_id.id: line.product_qty
            for line in self.bom_id.with_context(active_test=False).bom_line_ids
        }
        new_lines = {
            line.product_id.id: line.product_qty
            for line in self.new_bom_id.with_context(active_test=False).bom_line_ids
        }

        changes = []
        for product_id in set(old_lines.keys()) | set(new_lines.keys()):
            old_qty = old_lines.get(product_id, 0.0)
            new_qty = new_lines.get(product_id, 0.0)

            if old_qty == 0 and new_qty > 0:
                change_type = 'add'
            elif old_qty > 0 and new_qty == 0:
                change_type = 'remove'
            elif old_qty != new_qty:
                change_type = 'update'
            else:
                continue

            changes.append({
                'eco_id': self.id,
                'change_type': change_type,
                'product_id': product_id,
                'old_qty': old_qty,
                'new_qty': new_qty,
            })

        if changes:
            self.env['mrp.eco.bom.change'].create(changes)

        return {
            'name': _('ECO Changes Summary'),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.eco.bom.change',
            'view_mode': 'list',
            'domain': [('eco_id', '=', self.id)],
            'target': 'current',
        }

    def action_open_documents(self):
        self.ensure_one()
        return {
            'name': _('Documents'),
            'type': 'ir.actions.act_window',
            'res_model': 'ir.attachment',
            'view_mode': 'kanban,list,form',
            'domain': [('res_model', '=', 'mrp.eco'), ('res_id', '=', self.id)],
            'context': {'default_res_model': 'mrp.eco', 'default_res_id': self.id},
        }

    def action_open_new_bom(self):
        self.ensure_one()
        if self.new_bom_id:
            # Use active_test=False since draft revision BoM is archived
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'mrp.bom',
                'res_id': self.new_bom_id.id,
                'view_mode': 'form',
                'context': {'active_test': False},
            }

    def action_approve(self):
        for eco in self:
            for approval in eco.approval_ids.filtered(lambda a: a.status == 'none'):
                if self.env.user in approval.approval_template_id.user_ids:
                    approval.action_approve()

    def action_reject(self):
        for eco in self:
            for approval in eco.approval_ids.filtered(lambda a: a.status == 'none'):
                if self.env.user in approval.approval_template_id.user_ids:
                    approval.action_reject()
