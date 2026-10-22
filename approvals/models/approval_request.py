# -*- coding: utf-8 -*-
# pyrefly: ignore [missing-import]
from odoo import api, fields, models, _
# pyrefly: ignore [missing-import]
from odoo.exceptions import UserError, ValidationError


class ApprovalRequest(models.Model):
    _name = 'approval.request'
    _description = 'Approval Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Subject', required=True, tracking=True)
    reference = fields.Char(string='Reference')
    category_id = fields.Many2one(
        'approval.category', string='Category', required=True,
        tracking=True, ondelete='restrict')
    company_id = fields.Many2one(
        'res.company', string='Company', related='category_id.company_id',
        store=True, readonly=True)
    request_owner_id = fields.Many2one(
        'res.users', string='Created by', default=lambda self: self.env.user,
        tracking=True)
    date_confirmed = fields.Datetime(string='Confirmed On')

    request_status = fields.Selection([
        ('draft', 'To Submit'),
        ('pending', 'Submitted'),
        ('approved', 'Approved'),
        ('refused', 'Refused'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, required=True,
       copy=False, group_expand='_read_group_request_status')

    @api.model
    def _read_group_request_status(self, *args, **kwargs):
        return [key for key, val in type(self).request_status.selection]

    approver_ids = fields.One2many(
        'approval.approver', 'request_id', string='Approvers', copy=True)
    my_activity_status = fields.Char(compute='_compute_my_activity_status')
    
    category_image = fields.Image(related='category_id.image', readonly=True)
    description = fields.Html(string='Description')

    # Optional descriptive fields, shown based on category configuration
    date = fields.Datetime(string='Date')
    date_start = fields.Datetime(string='Date Start')
    date_end = fields.Datetime(string='Date End')
    location = fields.Char(string='Location')
    quantity = fields.Float(string='Quantity', default=1.0)
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id)
    payment_method_id = fields.Many2one(
        'account.payment.method', string='Payment Method')
    partner_id = fields.Many2one('res.partner', string='Contact')

    product_line_ids = fields.One2many(
        'approval.product.line', 'request_id', string='Product Lines')
    attachment_ids = fields.One2many(
        'ir.attachment', 'res_id', string='Attachments',
        domain=lambda self: [('res_model', '=', 'approval.request')])
    attachment_number = fields.Integer(compute='_compute_attachment_number')

    has_product = fields.Boolean(related='category_id.has_variant')
    line_type = fields.Selection(related='category_id.line_type')
    has_date = fields.Selection(related="category_id.date")
    has_date_start = fields.Selection(related="category_id.date_start")
    has_date_end = fields.Selection(related="category_id.date_start")
    has_location = fields.Selection(related="category_id.location")
    has_amount = fields.Selection(related="category_id.amount")
    has_reference = fields.Selection(related="category_id.reference")
    has_partner = fields.Selection(related="category_id.has_partner")
    has_payment_method = fields.Selection(related="category_id.payment_method")
    create_rfq = fields.Boolean(related="category_id.create_rfq")
    purchase_order_ids = fields.Many2many('purchase.order', string='Purchase Orders', groups='purchase.group_purchase_user')
    purchase_order_count = fields.Integer(compute='_compute_purchase_order_count', groups='purchase.group_purchase_user')
    _check_name_unique = models.Constraint(
        'UNIQUE(reference, company_id)',
        'The reference must be unique per company.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name'):
                vals['name'] = self.env['ir.sequence'].next_by_code('approval.request') or 'New'
                
            # Auto-generate approvers if created via API/backend and none are provided
            if 'approver_ids' not in vals and vals.get('category_id'):
                category = self.env['approval.category'].browse(vals['category_id'])
                approvers = []
                for i, category_approver in enumerate(category.user_ids):
                    approvers.append((0, 0, {
                        'user_id': category_approver.user_id.id,
                        'sequence': i + 1,
                        'required': category_approver.required,
                    }))
                owner_id = vals.get('request_owner_id', self.env.user.id)
                if category.is_manager_approver and owner_id:
                    employee = self.env['hr.employee'].search([('user_id', '=', owner_id)], limit=1) if 'hr.employee' in self.env else False
                    manager = employee.parent_id.user_id if employee and employee.parent_id else False
                    if manager:
                        approvers.append((0, 0, {
                            'user_id': manager.id,
                            'sequence': 0,
                            'required': True,
                            'is_manager': True,
                        }))
                if approvers:
                    vals['approver_ids'] = approvers

        return super().create(vals_list)

    def write(self, vals):
        locked_fields = {
            'name', 'category_id', 'date', 'date_start', 'date_end', 
            'location', 'quantity', 'amount', 'currency_id', 
            'payment_method_id', 'partner_id', 'reference', 
            'product_line_ids', 'description', 'request_owner_id'
        }
        if any(field in vals for field in locked_fields):
            for request in self:
                if request.request_status != 'draft':
                    raise UserError(_("You cannot modify the details of a request that has already been submitted."))
        return super(ApprovalRequest, self).write(vals)

    def _compute_attachment_number(self):
        for request in self:
            request.attachment_number = 0
        if not self.ids:
            return
        attachment_data = self.env['ir.attachment']._read_group([
            ('res_model', '=', 'approval.request'),
            ('res_id', 'in', self.ids),
        ], groupby=['res_id'], aggregates=['__count'])
        mapped_data = {res_id: count for res_id, count in attachment_data}
        for request in self:
            request.attachment_number = mapped_data.get(request.id, 0)

    def _compute_purchase_order_count(self):
        for request in self:
            request.purchase_order_count = len(request.purchase_order_ids)

    def _compute_my_activity_status(self):
        for request in self:
            approver = request.approver_ids.filtered(
                lambda a: a.user_id == self.env.user)
            request.my_activity_status = approver[:1].status or ''

    @api.onchange('category_id', 'request_owner_id')
    def _onchange_category_id(self):
        if self.category_id:
            approvers = []
            for i, category_approver in enumerate(self.category_id.user_ids):
                approvers.append((0, 0, {
                    'user_id': category_approver.user_id.id,
                    'sequence': i + 1,
                    'required': category_approver.required,
                }))
            if self.category_id.is_manager_approver and self.request_owner_id:
                employee = self.env['hr.employee'].search([('user_id', '=', self.request_owner_id.id)], limit=1) if 'hr.employee' in self.env else False
                manager = employee.parent_id.user_id if employee and employee.parent_id else False
                if manager:
                    approvers.append((0, 0, {
                        'user_id': manager.id,
                        'sequence': 0,
                        'required': True,
                        'is_manager': True,
                    }))
            self.approver_ids = [(5, 0, 0)] + approvers

    def action_confirm(self):
        for request in self:
            cat = request.category_id
            

            missing = []
            
            if cat.has_partner == 'required' and not request.partner_id:
                missing.append(_('Contact'))
            if cat.date == 'required' and not request.date:
                missing.append(_('Date'))
            if cat.date_start == 'required' and not request.date_start:
                missing.append(_('Date Start'))
            if cat.date_end == 'required' and not request.date_end:
                missing.append(_('Date End'))
            if cat.location == 'required' and not request.location:
                missing.append(_('Location'))
            if cat.reference == 'required' and not request.reference:
                missing.append(_('Reference'))
            if cat.payment_method == 'required' and not request.payment_method_id:
                missing.append(_('Payment Method'))
            if cat.line_type == 'required' and not request.product_line_ids:
                missing.append(_('Products'))
            if cat.requirer_document == 'required' and request.attachment_number <= 0:
                missing.append(_('Supporting Document (Attachment)'))
                
            if missing:
                raise UserError(_('You must provide the following required fields before submitting this request:\n- %s') % '\n- '.join(missing))

            if not request.approver_ids:
                raise UserError(_(
                    'You need to add at least one approver to submit this '
                    'request for approval.'))
            if len(request.approver_ids) < cat.approval_minimum:
                raise UserError(_(
                    'You have assigned %s approver(s), but this category requires a minimum of %s approvals.'
                ) % (len(request.approver_ids), cat.approval_minimum))
            if cat.approval_type == 'sequence':
                sorted_approvers = request.approver_ids.sorted('sequence')
                if sorted_approvers:
                    sorted_approvers[0].write({'status': 'pending'})
                    if len(sorted_approvers) > 1:
                        sorted_approvers[1:].write({'status': 'new'})
            else:
                request.approver_ids.write({'status': 'pending'})
            request.write({
                'request_status': 'pending',
                'date_confirmed': fields.Datetime.now(),
            })
            request._notify_approvers()

    def _notify_approvers(self):
        for request in self:
            approvers = request._get_current_approvers()
            for approver in approvers:
                request.activity_schedule(
                    'approvals.mail_activity_type_approval',
                    summary=_('Approval Requested: %s') % request.name,
                    user_id=approver.user_id.id,
                )
                
                # Notify via chatter/email
                partner = approver.user_id.partner_id
                if partner:
                    request.message_subscribe(partner_ids=[partner.id])
                    request.message_post(
                        body=_("Action Required: Please review this new request."),
                        partner_ids=[partner.id],
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment'
                    )

    def action_create_rfq(self):
        self.ensure_one()
        if self.request_status != 'approved':
            raise UserError(_("You cannot create a Request for Quotation until the Approval Request has been fully approved."))
        if not self.product_line_ids:
            raise UserError(_("You must have at least one product line to create a Request for Quotation."))
        
        vendors_dict = {}
        for line in self.product_line_ids:
            vendor = self.partner_id
            if not vendor:
                sellers = line.product_id.seller_ids
                if sellers:
                    vendor = sellers[0].partner_id
                else:
                    raise UserError(_(
                        "Please select a Contact on the request, or configure a Vendor directly on the product: %s",
                        line.product_id.display_name
                    ))
            
            if vendor not in vendors_dict:
                vendors_dict[vendor] = []
                
            vendors_dict[vendor].append((0, 0, {
                'product_id': line.product_id.id,
                'product_qty': line.quantity,
                'uom_id': line.product_uom_id.id or line.product_id.uom_id.id,
                'price_unit': line.price_unit,
                'name': line.description or line.product_id.display_name,
            }))
            
        po_ids = []
        for vendor, po_lines in vendors_dict.items():
            po = self.env['purchase.order'].create({
                'partner_id': vendor.id,
                'order_line': po_lines,
            })
            po_ids.append(po.id)
            
        self.purchase_order_ids = [(4, po_id) for po_id in po_ids]
        
    def action_view_purchase_orders(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('purchase.purchase_rfq')
        action['domain'] = [('id', 'in', self.purchase_order_ids.ids)]
        action['context'] = {'default_partner_id': self.partner_id.id}
        if len(self.purchase_order_ids) == 1:
            action['views'] = [(self.env.ref('purchase.purchase_order_form').id, 'form')]
            action['res_id'] = self.purchase_order_ids[0].id
        return action

    def _get_current_approvers(self):
        """Return the approvers who currently need to act, depending on
        whether the category uses sequential or 'any approver' logic."""
        self.ensure_one()
        pending = self.approver_ids.filtered(lambda a: a.status == 'pending')
        if self.category_id.approval_type == 'sequence':
            pending = pending.sorted('sequence')
            if pending:
                return pending[:1]
            return self.env['approval.approver']
        return pending

    def _check_approval_status(self):
        for request in self:
            approvers = request.approver_ids
            if any(a.status == 'refused' for a in approvers):
                request.write({'request_status': 'refused'})
                continue

            approved_count = len(approvers.filtered(lambda a: a.status == 'approved'))
            pending_required = any(a.required and a.status != 'approved' for a in approvers)
            
            is_approved = (approved_count >= request.category_id.approval_minimum and not pending_required)

            if request.category_id.approval_type == 'sequence' and not is_approved:
                # advance to next approver in sequence if current one approved and request is not fully approved
                next_approver = approvers.filtered(
                    lambda a: a.status == 'new').sorted('sequence')[:1]
                last_decided = approvers.filtered(
                    lambda a: a.status == 'approved').sorted('sequence')
                if next_approver and last_decided:
                    next_approver.write({'status': 'pending'})
                    request._notify_approvers()

            if is_approved:
                request.write({'request_status': 'approved'})

    def action_approve(self):
        for request in self:
            approver = request.approver_ids.filtered(
                lambda a: a.user_id == self.env.user and a.status == 'pending')
            if not approver:
                raise UserError(_('You are not allowed to approve this request.'))
            approver.action_approve()

    def action_refuse(self):
        for request in self:
            approver = request.approver_ids.filtered(
                lambda a: a.user_id == self.env.user and a.status == 'pending')
            if not approver:
                raise UserError(_('You are not allowed to refuse this request.'))
            approver.action_refuse()

    def action_withdraw(self):
        """Send back to draft."""
        for request in self:
            request.approver_ids.write({'status': 'new'})
            request.write({'request_status': 'draft'})

    def action_cancel(self):
        for request in self:
            request.approver_ids.filtered(
                lambda a: a.status == 'pending').write({'status': 'cancel'})
            request.write({'request_status': 'cancel'})

    def action_draft(self):
        for request in self:
            request.approver_ids.write({'status': 'new'})
            request.write({'request_status': 'draft'})

    def action_view_attachments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Attachments'),
            'res_model': 'ir.attachment',
            'view_mode': 'kanban,list,form',
            'domain': [('res_model', '=', 'approval.request'), ('res_id', '=', self.id)],
            'context': {'default_res_model': 'approval.request', 'default_res_id': self.id},
        }
