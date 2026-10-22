import datetime
from PIL import Image
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError
from markupsafe import Markup

class DMSFile(models.Model):
    _inherit = "dms.file"

    @api.depends("mimetype", "content", "current_revision_id.content")
    def _compute_image_1920(self):
        """Provide thumbnail automatically for active version."""
        for one in self:
            active_content = one.current_revision_id.content if one.current_revision_id and one.current_revision_id.content else one.content
            if one.mimetype != "application/pdf" and one.mimetype in (
                *Image.MIME.values(),
                "image/svg+xml",
            ):
                one.image_1920 = active_content
            else:
                one.image_1920 = False

    # Document Controller Fields
    directory_id = fields.Many2one(
        comodel_name="dms.directory",
        domain="[('permission_upload', '=', True)]",
        required=False,
    )
    document_number = fields.Char(
        string="Document Number",
        readonly=True,
        copy=False,
        default=lambda self: _('New')
    )
    file_type_display = fields.Char(
        string="File Type",
        compute="_compute_file_type_display",
    )

    @api.depends("extension", "mimetype", "name")
    def _compute_file_type_display(self):
        MIME_MAP = {
            "pdf": _("PDF Document"),
            "docx": _("Word Document"),
            "doc": _("Word Document"),
            "xlsx": _("Excel Spreadsheet"),
            "xls": _("Excel Spreadsheet"),
            "pptx": _("PowerPoint Presentation"),
            "ppt": _("PowerPoint Presentation"),
            "txt": _("Text Document"),
            "csv": _("CSV Spreadsheet"),
            "zip": _("ZIP Archive"),
            "rar": _("RAR Archive"),
            "7z": _("7-Zip Archive"),
            "tar": _("TAR Archive"),
            "gz": _("GZip Archive"),
            "png": _("PNG Image"),
            "jpg": _("JPEG Image"),
            "jpeg": _("JPEG Image"),
            "gif": _("GIF Image"),
            "webp": _("WebP Image"),
            "svg": _("SVG Vector Graphic"),
            "mp4": _("MP4 Video"),
            "mkv": _("MKV Video"),
            "avi": _("AVI Video"),
            "mov": _("MOV Video"),
            "mp3": _("MP3 Audio"),
            "wav": _("WAV Audio"),
            "json": _("JSON File"),
            "xml": _("XML Document"),
            "html": _("HTML Webpage"),
        }
        for rec in self:
            ext = (rec.extension or '').lower().strip('.')
            if not ext and rec.name and '.' in rec.name:
                ext = rec.name.split('.')[-1].lower()

            if ext in MIME_MAP:
                rec.file_type_display = f"{MIME_MAP[ext]} (.{ext})"
            elif rec.mimetype and rec.mimetype.startswith("image/"):
                rec.file_type_display = _("%s Image (.%s)") % (ext.upper() if ext else "Raster", ext or "img")
            elif rec.mimetype and rec.mimetype.startswith("video/"):
                rec.file_type_display = _("%s Video (.%s)") % (ext.upper() if ext else "Media", ext or "vid")
            elif rec.mimetype and rec.mimetype.startswith("audio/"):
                rec.file_type_display = _("%s Audio (.%s)") % (ext.upper() if ext else "Sound", ext or "aud")
            elif ext:
                rec.file_type_display = _("%s File (.%s)") % (ext.upper(), ext)
            elif rec.mimetype and rec.mimetype != "application/octet-stream":
                rec.file_type_display = rec.mimetype
            else:
                rec.file_type_display = _("Binary File")


    @api.model
    def search_panel_select_range(self, field_name, **kwargs):
        res = super().search_panel_select_range(field_name, **kwargs)
        if isinstance(res, dict) and field_name == 'directory_id' and 'values' in res:
            directory_ids = [v['id'] for v in res['values'] if isinstance(v, dict) and 'id' in v]
            directories = self.env['dms.directory'].browse(directory_ids)
            file_data = self.env['dms.file']._read_group(
                [('directory_id', 'in', directory_ids), ('is_trashed', '=', False)],
                groupby=['directory_id'],
                aggregates=['__count']
            )
            file_counts = {dir_rec.id: count for dir_rec, count in file_data}
            dir_permissions = {
                d.id: {
                    'permission_download': d.permission_download,
                    'permission_write': d.permission_write,
                    'permission_unlink': d.permission_unlink,
                    'permission_move': d.permission_move,
                    'count_files': file_counts.get(d.id, 0),
                } for d in directories
            }
            for v in res['values']:
                if isinstance(v, dict) and 'id' in v:
                    perms = dir_permissions.get(v['id'], {})
                    v.update(perms)
                    v['__count'] = perms.get('count_files', 0)
        return res

    @api.model
    def search_panel_select_multi_range(self, field_name, **kwargs):
        res = super().search_panel_select_multi_range(field_name, **kwargs)
        if isinstance(res, list):
            res = {"values": res}
        elif not isinstance(res, dict):
            res = {"values": []}
        elif "values" not in res:
            res["values"] = []
        return res

    @api.model
    def get_upload_config(self):
        """Return upload constraints for client-side validation before upload."""
        max_size_mb = self._get_binary_max_size()
        forbidden_extensions = [
            ext.strip().lower().lstrip('.')
            for ext in self._get_forbidden_extensions()
            if ext.strip()
        ]
        return {
            'max_size_mb': max_size_mb,
            'forbidden_extensions': forbidden_extensions,
        }

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # The Search Panel often injects default_directory_id = False if "All" is selected in the sidebar.
        # This overrides our original action context and prevents autofill.
        # We manually recover it here from other context keys if it evaluates to False.
        if 'directory_id' in fields_list and not res.get('directory_id'):
            recovered_id = self.env.context.get('searchpanel_default_directory_id')
            
            # Fallback to active_id if we came from a directory form
            if not recovered_id and self.env.context.get('active_model') == 'dms.directory':
                recovered_id = self.env.context.get('active_id')
                
            if recovered_id:
                res['directory_id'] = recovered_id
        return res
    access_ids = fields.One2many(
        comodel_name="dms.file.access",
        inverse_name="file_id",
        string="All Access Rights",
    )
    group_access_ids = fields.One2many(
        comodel_name="dms.file.access",
        inverse_name="file_id",
        domain=[("group_id", "!=", False)],
        string="User Group Access Rights",
    )
    partner_access_ids = fields.One2many(
        comodel_name="dms.file.access",
        inverse_name="file_id",
        domain=[("group_id", "=", False)],
        string="Contact Access Rights",
    )
    department_id = fields.Many2one(
        comodel_name="hr.department",
        string="Department"
    )
    document_owner_id = fields.Many2one(
        comodel_name="res.users",
        string="Document Owner",
        default=lambda self: self.env.user
    )

    def action_open_owner(self):
        self.ensure_one()
        owner = self.document_owner_id or self.create_uid
        if not owner:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': owner.name,
            'res_model': 'res.users',
            'res_id': owner.id,
            'views': [[False, 'form']],
            'target': 'current',
        }
    confidentiality = fields.Selection(
        selection=[
            ('public', 'Public'),
            ('internal', 'Internal'),
            ('confidential', 'Confidential'),
            ('restricted', 'Restricted')
        ],
        string="Confidentiality",
        default='internal'
    )
    share_internal_access = fields.Selection(
        selection=[
            ('none', 'None'),
            ('viewer', 'Viewer'),
            ('editor', 'Editor'),
        ],
        string="Internal Users Access",
        default='none',
    )
    share_link_access = fields.Selection(
        selection=[
            ('none', 'None'),
            ('viewer', 'Viewer'),
            ('editor', 'Editor'),
        ],
        string="Access Through Link",
        default='viewer',
    )
    share_is_discoverable = fields.Selection(
        selection=[
            ('no', 'No'),
            ('yes', 'Yes'),
        ],
        string="Discoverable",
        default='no',
    )
    share_link_url = fields.Char(
        string="Share Link",
        compute="_compute_share_link_url",
    )

    def _compute_share_link_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        dbname = self.env.cr.dbname
        for record in self:
            token = record._portal_ensure_token() if hasattr(record, '_portal_ensure_token') else record.access_token
            if not token:
                if hasattr(record, '_portal_ensure_token'):
                    token = record._portal_ensure_token()
                else:
                    import secrets
                    token = secrets.token_urlsafe(20)
                    record.sudo().write({'access_token': token})
            record.share_link_url = f"{base_url.rstrip('/')}/dms/share/file/{token}?db={dbname}"

    @api.model
    def _register_hook(self):
        res = super()._register_hook()
        try:
            from ..http_patch import apply_http_patch
            apply_http_patch()
        except Exception:
            pass
        return res

    @api.model
    def action_apply_router_patch(self):
        import importlib
        import sys
        if 'dms_enterprise_features.http_patch' in sys.modules:
            importlib.reload(sys.modules['dms_enterprise_features.http_patch'])
        from ..http_patch import apply_http_patch
        apply_http_patch()
        from odoo.http import router
        return getattr(router._set_session_and_dbname, '__name__', 'None')

    def action_open_share_wizard(self):
        self.ensure_one()
        if self.is_locked and not self.is_lock_editor and not self.env.user.has_group('dms.group_dms_manager') and not self.env.su:
            raise UserError(_("'%s' is locked by %s. Only the locking user or a DMS Manager can share it.") % (self.name, self.locked_by.name or 'another user'))
        return {
            'name': _('Share: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'dms.file.share.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'dialog_size': 'md',
                'default_file_id': self.id,
            },
        }

    expiry_date = fields.Date(string="Expiry Date")
    notify_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Notify User",
        help="Person to notify before expiration."
    )
    notify_before_days = fields.Integer(
        string="Notify Before (Days)",
        default=7,
        help="Number of days prior to expiration to notify the user."
    )
    expiry_notification_sent = fields.Boolean(
        string="Expiration Notification Sent",
        default=False,
        copy=False
    )
    status = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('in_approval', 'In Approval'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('obsolete', 'Obsolete')
        ],
        string="Status",
        default='draft',
        tracking=True
    )

    # Trash Management
    is_trashed = fields.Boolean(
        string="In Trash",
        default=False,
        tracking=True
    )
    trash_date = fields.Datetime(
        string="Trash Date"
    )
    directory_is_trashed = fields.Boolean(
        related='directory_id.is_trashed',
        string="Directory is Trashed"
    )
    starred = fields.Boolean(
        string="Starred",
        default=False,
        tracking=True
    )

    
    revision_ids = fields.One2many(
        comodel_name="dms.file.revision",
        inverse_name="file_id",
        string="Revisions",
        context={'active_test': False}
    )
    current_revision_id = fields.Many2one(
        comodel_name="dms.file.revision",
        string="Current Revision",
        readonly=True
    )
    approval_ids = fields.One2many(
        comodel_name="dms.file.approval",
        inverse_name="file_id",
        string="Approvals",
    )
    is_sequential_approval = fields.Boolean(
        string="Sequential Approval",
        default=True,
        help="If enabled, approvers will be requested one by one in sequence. If disabled, all approvers will be requested simultaneously.",
    )
    approval_state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('in_approval', 'In Approval'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        string="Approval Status",
        default='draft',
        tracking=True,
    )
    current_approver_ids = fields.Many2many(
        comodel_name="res.users",
        compute="_compute_approval_info",
        search="_search_current_approver_ids",
        string="Pending Approvers",
    )
    is_current_approver = fields.Boolean(
        string="Is Current Approver",
        compute="_compute_approval_info",
    )
    rejection_reason = fields.Text(
        string="Rejection Reason",
        compute="_compute_approval_info",
    )
    rejected_by = fields.Many2one(
        comodel_name="res.users",
        compute="_compute_approval_info",
        string="Rejected By",
    )

    is_my_file = fields.Boolean(
        string="Is My File",
        compute="_compute_is_my_file",
        search="_search_is_my_file",
    )

    def _compute_is_my_file(self):
        uid = self.env.uid
        user = self.env.user
        partner_id = user.partner_id.id if user.partner_id else 0
        groups = getattr(user, 'group_ids', getattr(user, 'groups_id', self.env['res.groups']))
        user_group_ids = groups.ids
        for record in self:
            is_creator = record.create_uid.id == uid
            is_owner = record.document_owner_id.id == uid if record.document_owner_id else False
            is_approver = uid in record.approval_ids.mapped('approver_id.id')
            has_access = any(
                a.user_id.id == uid or (a.partner_id and a.partner_id.id == partner_id) or (a.group_id and a.group_id.id in user_group_ids)
                for a in record.access_ids
            )
            record.is_my_file = bool(is_creator or is_owner or is_approver or has_access)

    def _search_is_my_file(self, operator, value):
        from odoo.fields import Domain
        OR = Domain.OR
        uid = self.env.uid
        partner_id = self.env.user.partner_id.id if self.env.user.partner_id else 0
        groups = getattr(self.env.user, 'group_ids', getattr(self.env.user, 'groups_id', self.env['res.groups']))
        group_ids = groups.ids
        domains = [
            [('create_uid', '=', uid)],
            [('document_owner_id', '=', uid)],
            [('approval_ids.approver_id', '=', uid)],
            [('access_ids.user_id', '=', uid)],
            [('access_ids.partner_id', '=', partner_id)],
        ]
        if group_ids:
            domains.append([('access_ids.group_id', 'in', group_ids)])
            
        positive_domain = OR(domains)
        
        is_positive = False
        if operator == '=' and value:
            is_positive = True
        elif operator in ('in', 'child_of'):
            if isinstance(value, (list, tuple, set)) or hasattr(value, '__iter__'):
                is_positive = any(bool(v) for v in value)
            else:
                is_positive = bool(value)
        elif operator == '!=' and not value:
            is_positive = True

        if is_positive:
            return positive_domain
        else:
            return ['!', *positive_domain]

    def _search_current_approver_ids(self, operator, value):
        if operator in ('in', '=', '!=', 'not in'):
            steps = self.env['dms.file.approval'].sudo().search([
                ('status', '=', 'pending'),
                ('approver_id', operator, value)
            ])
            return [('id', 'in', steps.mapped('file_id').ids), ('approval_state', '=', 'in_approval')]
        return []

    @api.depends('approval_ids.status', 'approval_ids.comments', 'approval_state')
    def _compute_approval_info(self):
        current_uid = self.env.uid
        for record in self:
            pending_steps = record.approval_ids.filtered(lambda a: a.status == 'pending')
            pending_users = pending_steps.mapped('approver_id')
            record.current_approver_ids = pending_users
            record.is_current_approver = (
                record.approval_state == 'in_approval'
                and current_uid in pending_users.ids
            )
            
            # Rejection info
            rejected_step = record.approval_ids.filtered(lambda a: a.status == 'rejected')[:1]
            if rejected_step:
                record.rejection_reason = rejected_step.comments or False
                record.rejected_by = rejected_step.approver_id
            else:
                record.rejection_reason = False
                record.rejected_by = False

    def action_request_approval(self):
        for record in self:
            if record.is_locked and not record.is_lock_editor and not self.env.user.has_group('dms.group_dms_manager') and not self.env.su:
                raise UserError(_("Cannot request approval because '%s' is locked by %s.") % (record.name, record.locked_by.name or 'another user'))
            if not record.approval_ids:
                owner = record.document_owner_id or self.env.user
                if owner.default_approval_ids:
                    record.write({
                        'is_sequential_approval': owner.default_is_sequential_approval,
                        'approval_ids': [(0, 0, {
                            'sequence': s.sequence,
                            'approver_id': s.approver_id.id,
                            'status': 'draft',
                        }) for s in owner.default_approval_ids]
                    })
                else:
                    raise UserError(_("Please add at least one approver in the Approvals tab before requesting approval."))

            # Reset any prior completed state on steps
            for step in record.approval_ids:
                step.sudo().write({
                    'status': 'draft',
                    'date': False,
                    'comments': False,
                })

            # Clear any old approval activities
            activities = self.env['mail.activity'].sudo().search([
                ('res_id', '=', record.id),
                ('res_model', '=', 'dms.file'),
            ])
            activities.unlink()

            if record.is_sequential_approval:
                sorted_steps = record.approval_ids.sorted(key=lambda s: (s.sequence, s.id))
                first_step = sorted_steps[0]
                first_step.sudo().write({'status': 'pending'})
                for other in sorted_steps[1:]:
                    other.sudo().write({'status': 'waiting'})

                record._notify_approver(first_step.approver_id)
                approver_names = first_step.approver_id.name
            else:
                for step in record.approval_ids:
                    step.sudo().write({'status': 'pending'})
                    record._notify_approver(step.approver_id)
                approver_names = ", ".join(record.approval_ids.mapped('approver_id.name'))

            record.sudo().write({'approval_state': 'in_approval'})
            record.sudo().message_post(
                body=Markup(_("Approval requested. Waiting for: <strong>%s</strong> (Mode: %s)")) % (
                    approver_names,
                    _("Sequential") if record.is_sequential_approval else _("Parallel")
                ),
                subtype_xmlid="mail.mt_note"
            )

    def action_load_default_approvers(self):
        for record in self:
            if record.approval_state not in ('draft', 'rejected'):
                raise UserError(_("You can only load default approvers on draft or rejected documents."))
            owner = record.document_owner_id or self.env.user
            if owner.default_approval_ids:
                record.write({
                    'is_sequential_approval': owner.default_is_sequential_approval,
                    'approval_ids': [(5, 0, 0)] + [(0, 0, {
                        'sequence': s.sequence,
                        'approver_id': s.approver_id.id,
                        'status': 'draft',
                    }) for s in owner.default_approval_ids]
                })
            else:
                raise UserError(_("No default approvers configured for %s.") % owner.name)

    def _notify_approver(self, approver_user):
        self.ensure_one()
        try:
            self.env['mail.activity'].sudo().create({
                'res_id': self.id,
                'res_model_id': self.env['ir.model']._get('dms.file').id,
                'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                'summary': _('Document Approval Request: %s') % self.name,
                'note': Markup(_('Please review and approve the document <strong>%s</strong>.')) % self.name,
                'user_id': approver_user.id,
            })
        except Exception:
            pass

    def action_approve_step(self, approver_user=False):
        user = approver_user or self.env.user
        for record in self:
            if record.approval_state != 'in_approval':
                raise UserError(_("This document is not currently awaiting approval."))

            pending_step = record.approval_ids.filtered(lambda s: s.status == 'pending' and s.approver_id == user)[:1]
            if not pending_step:
                raise UserError(_("Only the assigned approver can approve this step."))

            pending_step.sudo().write({
                'status': 'approved',
                'date': fields.Datetime.now(),
            })

            # Mark activity done
            activities = self.env['mail.activity'].sudo().search([
                ('res_id', '=', record.id),
                ('res_model', '=', 'dms.file'),
                ('user_id', '=', pending_step.approver_id.id),
            ])
            activities.action_feedback(feedback=_("Approved"))

            record.sudo().message_post(
                body=Markup(_("Approved step for <strong>%s</strong>.")) % pending_step.approver_id.name,
                subtype_xmlid="mail.mt_note"
            )

            if record.is_sequential_approval:
                waiting_steps = record.approval_ids.filtered(lambda s: s.status == 'waiting').sorted(key=lambda s: (s.sequence, s.id))
                if waiting_steps:
                    next_step = waiting_steps[0]
                    next_step.sudo().write({'status': 'pending'})
                    record._notify_approver(next_step.approver_id)
                    record.sudo().message_post(
                        body=Markup(_("Next approval step activated for <strong>%s</strong>.")) % next_step.approver_id.name,
                        subtype_xmlid="mail.mt_note"
                    )
                else:
                    record._on_fully_approved()
            else:
                unfinished = record.approval_ids.filtered(lambda s: s.status in ('pending', 'waiting', 'draft'))
                if not unfinished:
                    record._on_fully_approved()

    def _on_fully_approved(self):
        for record in self:
            # Option B: Keep in original folder, set approved state
            record.sudo().with_context(dms_skip_log=True).write({'approval_state': 'approved'})
            self.env['dms.file.log'].sudo().create({
                'name': record.name,
                'file_id': record.id,
                'action': 'edit',
                'details': "Document fully approved"
            })

            owner = record.document_owner_id or record.create_uid
            if owner:
                try:
                    self.env['mail.activity'].sudo().create({
                        'res_id': record.id,
                        'res_model_id': self.env['ir.model']._get('dms.file').id,
                        'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                        'summary': _('Document Approved: %s') % record.name,
                        'note': Markup(_('Your document <strong>%s</strong> has been fully approved.')) % record.name,
                        'user_id': owner.id,
                    })
                except Exception:
                    pass

            record.sudo().message_post(
                body=Markup(_("🎉 <strong>Document Fully Approved!</strong>")),
                subtype_xmlid="mail.mt_note"
            )

    def _ensure_approval_directory(self):
        self.ensure_one()
        approval_root = self.env['dms.directory'].sudo().search([
            ('name', '=', 'Approval'),
            ('parent_id', '=', False),
            ('is_trashed', '=', False),
        ], limit=1)

        if not approval_root:
            storage = self.env.ref('dms_enterprise_features.dms_storage_enterprise', raise_if_not_found=False) or self.env['dms.storage'].search([], limit=1)
            approval_root = self.env['dms.directory'].sudo().create({
                'name': 'Approval',
                'is_root_directory': True,
                'storage_id': storage.id if storage else False,
            })

        owner_name = (self.document_owner_id.name or self.create_uid.name or 'General').strip()
        user_folder = self.env['dms.directory'].sudo().search([
            ('name', '=', owner_name),
            ('parent_id', '=', approval_root.id),
            ('is_trashed', '=', False),
        ], limit=1)

        if not user_folder:
            user_folder = self.env['dms.directory'].sudo().create({
                'name': owner_name,
                'parent_id': approval_root.id,
                'is_root_directory': False,
                'storage_id': approval_root.storage_id.id if approval_root.storage_id else False,
            })

        return user_folder

    def action_open_reject_wizard(self):
        self.ensure_one()
        return {
            'name': _('Reject Document: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'dms.file.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_file_id': self.id,
            }
        }

    def action_process_rejection(self, reason):
        for record in self:
            user = self.env.user
            pending_step = record.approval_ids.filtered(lambda s: s.status == 'pending' and s.approver_id == user)[:1]
            if not pending_step:
                raise UserError(_("Only the assigned approver can reject this step."))

            pending_step.sudo().write({
                'status': 'rejected',
                'date': fields.Datetime.now(),
                'comments': reason,
            })
            rejector_name = pending_step.approver_id.name

            # Set remaining pending/waiting to draft
            other_steps = record.approval_ids.filtered(lambda s: s.status in ('pending', 'waiting'))
            other_steps.sudo().write({'status': 'draft'})

            record.sudo().write({'approval_state': 'rejected'})

            # Clear activities
            activities = self.env['mail.activity'].sudo().search([
                ('res_id', '=', record.id),
                ('res_model', '=', 'dms.file'),
            ])
            activities.action_feedback(feedback=_("Rejected: %s") % reason)

            # Notify owner
            owner = record.document_owner_id or record.create_uid
            if owner:
                try:
                    self.env['mail.activity'].sudo().create({
                        'res_id': record.id,
                        'res_model_id': self.env['ir.model']._get('dms.file').id,
                        'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                        'summary': _('Document Rejected: %s') % record.name,
                        'note': Markup(_('Your document <strong>%s</strong> was rejected by <strong>%s</strong>.<br/><strong>Reason:</strong> %s')) % (record.name, rejector_name, reason),
                        'user_id': owner.id,
                    })
                except Exception:
                    pass

            # Post in chatter
            record.sudo().message_post(
                body=Markup(_("Document Rejected by %s<br/><strong>Reason:</strong> %s")) % (rejector_name, reason),
                subtype_xmlid="mail.mt_note"
            )

    def action_reset_approval(self):
        for record in self:
            for step in record.approval_ids:
                step.sudo().write({
                    'status': 'draft',
                    'date': False,
                    'comments': False,
                })
            record.sudo().write({'approval_state': 'draft'})
            activities = self.env['mail.activity'].sudo().search([
                ('res_id', '=', record.id),
                ('res_model', '=', 'dms.file'),
            ])
            activities.unlink()
            record.sudo().message_post(
                body=_("Approval workflow reset to Draft."),
                subtype_xmlid="mail.mt_note"
            )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self._is_dms_privileged_user():
            raise AccessError(_("Only Documents Managers and Administrators are allowed to upload or create files."))
        for vals in vals_list:
            if vals.get('document_number', _('New')) == _('New'):
                vals['document_number'] = self.env['ir.sequence'].next_by_code('dms.file.document.number') or _('New')
            
            # Auto-assign to Dashboard if directory is empty (Odoo Enterprise behavior)
            if not vals.get('directory_id'):
                dashboard = self.env['dms.directory'].search([('name', '=', 'Dashboard')], limit=1)
                if not dashboard:
                    storage = self.env['dms.storage'].search([], limit=1)
                    if not storage:
                        raise UserError(_("No storage configured. Please create a storage first."))
                    dashboard = self.env['dms.directory'].create({
                        'name': 'Dashboard',
                        'is_root_directory': True,
                        'storage_id': storage.id,
                    })
                vals['directory_id'] = dashboard.id

            # Auto-populate default approvers if none supplied
            owner_id = vals.get('document_owner_id') or self.env.uid
            if owner_id and 'approval_ids' not in vals:
                owner = self.env['res.users'].browse(owner_id)
                if owner.default_approval_ids:
                    vals['approval_ids'] = [(0, 0, {
                        'sequence': s.sequence,
                        'approver_id': s.approver_id.id,
                        'status': 'draft',
                    }) for s in owner.default_approval_ids]
                    if 'is_sequential_approval' not in vals:
                        vals['is_sequential_approval'] = owner.default_is_sequential_approval
        
        records = super(DMSFile, self.with_context(dms_creating_file=True)).create(vals_list)
        for record in records:
            dir_name = record.directory_id.name or _("Root")
            self.env['dms.file.log'].sudo().create({
                'name': record.name,
                'file_id': record.id,
                'action': 'create',
                'details': _("Document uploaded into folder '%s'") % dir_name,
                'user_id': self.env.user.id,
                'date': fields.Datetime.now(),
            })
            if record.content and not record.revision_ids:
                uploader = self.env.user if not self.env.user._is_public() else (record.document_owner_id or record.create_uid or self.env.ref('base.user_admin'))
                rev = self.env['dms.file.revision'].sudo().create({
                    'file_id': record.id,
                    'version': '1.0',
                    'content': record.content,
                    'file_name': record.name,
                    'uploader_id': uploader.id if uploader else False,
                    'upload_date': fields.Datetime.now(),
                    'comments': _('Initial version'),
                    'is_current': True,
                })
                record.with_context(from_revert_revision=True, dms_skip_log=True).write({'current_revision_id': rev.id})
        return records

    def write(self, vals):
        is_lock_op = set(vals.keys()).issubset({'locked_by', 'is_locked', 'is_lock_editor'})
        is_manager = self.env.su or self.env.user.has_group('dms.group_dms_manager') or self.env.user.has_group('base.group_system')

        for record in self:
            if record.is_locked and not is_lock_op:
                if not record.is_lock_editor and not is_manager:
                    raise UserError(_("'%s' is locked by %s. You cannot modify, move, or delete it.") % (record.name, record.locked_by.name or 'another user'))
                if 'directory_id' in vals and vals.get('directory_id') != record.directory_id.id:
                    raise UserError(_("Cannot move '%s' because it is locked by %s. Please unlock it first.") % (record.name, record.locked_by.name or 'another user'))
                if 'is_trashed' in vals and vals.get('is_trashed'):
                    raise UserError(_("Cannot send '%s' to Trash because it is locked by %s. Please unlock it first.") % (record.name, record.locked_by.name or 'another user'))

            if not is_manager and not is_lock_op:
                if 'name' in vals and not record.permission_rename:
                    raise AccessError(_("You do not have permission to rename this file."))
                if 'directory_id' in vals and not record.permission_move:
                    raise AccessError(_("You do not have permission to move this file."))
                if ('content' in vals or 'file' in vals or 'attachment_id' in vals) and not record.permission_edit:
                    raise AccessError(_("You do not have permission to edit this file."))

        is_revert = self.env.context.get('from_revert_revision') or self.env.context.get('no_new_revision')
        has_new_content = 'content' in vals and vals.get('content') and not is_revert

        # Track previous values before write to detect meaningful changes
        records_pre = {}
        for rec in self:
            records_pre[rec.id] = {
                'name': rec.name,
                'directory_id': rec.directory_id,
                'category_id': rec.category_id,
                'department_id': rec.department_id,
                'document_owner_id': rec.document_owner_id,
                'approval_state': rec.approval_state,
                'is_trashed': rec.is_trashed,
                'active': rec.active,
                'expiration_date': getattr(rec, 'expiration_date', False),
            }

        res = super().write(vals)

        # Skip logging during file creation, technical contexts, or if explicitly bypassed
        skip_log = (
            self.env.context.get('dms_creating_file')
            or self.env.context.get('dms_skip_log')
            or self.env.context.get('tracking_disable')
            or self.env.context.get('install_mode')
        )

        for record in self:
            if not skip_log:
                pre = records_pre.get(record.id, {})
                changes = []

                if has_new_content and record.content:
                    changes.append(_("File content updated (new version)"))
                elif ('content' in vals or 'file' in vals) and not is_revert:
                    changes.append(_("File content updated"))

                if 'name' in vals and vals.get('name') and pre.get('name') and vals.get('name') != pre.get('name'):
                    changes.append(_("Renamed from '%s' to '%s'") % (pre.get('name'), vals.get('name')))

                if 'directory_id' in vals and pre.get('directory_id') and record.directory_id != pre.get('directory_id'):
                    old_folder = pre['directory_id'].name or _("Root")
                    new_folder = record.directory_id.name or _("Root")
                    changes.append(_("Moved from folder '%s' to '%s'") % (old_folder, new_folder))

                if 'category_id' in vals and record.category_id != pre.get('category_id'):
                    new_cat = record.category_id.name or _("None")
                    changes.append(_("Category set to '%s'") % new_cat)

                if 'department_id' in vals and record.department_id != pre.get('department_id'):
                    new_dept = record.department_id.name or _("None")
                    changes.append(_("Department set to '%s'") % new_dept)

                if 'document_owner_id' in vals and record.document_owner_id != pre.get('document_owner_id'):
                    new_owner = record.document_owner_id.name or _("None")
                    changes.append(_("Owner set to '%s'") % new_owner)

                if 'tag_ids' in vals:
                    changes.append(_("Tags modified"))

                if 'document_number' in vals and vals.get('document_number'):
                    changes.append(_("Document number set to '%s'") % vals.get('document_number'))

                if 'expiration_date' in vals and vals.get('expiration_date') != pre.get('expiration_date'):
                    changes.append(_("Expiration date set to %s") % vals.get('expiration_date'))

                if 'is_trashed' in vals and record.is_trashed != pre.get('is_trashed'):
                    changes.append(_("Moved to Trash") if record.is_trashed else _("Restored from Trash"))

                if 'approval_state' in vals and record.approval_state != pre.get('approval_state'):
                    changes.append(_("Approval status: %s") % record.approval_state.replace('_', ' ').title())

                if 'active' in vals and record.active != pre.get('active'):
                    changes.append(_("Unarchived") if record.active else _("Archived"))

                if changes:
                    # Debounce / Coalesce: find recent log by same user for this file within the last 60 seconds
                    recent_cutoff = fields.Datetime.now() - datetime.timedelta(seconds=60)
                    recent_log = self.env['dms.file.log'].sudo().search([
                        ('file_id', '=', record.id),
                        ('user_id', '=', self.env.user.id),
                        ('action', '=', 'edit'),
                        ('date', '>=', recent_cutoff),
                    ], order='date desc', limit=1)

                    if recent_log:
                        existing_parts = [p.strip() for p in (recent_log.details or '').split('; ') if p.strip()]
                        for ch in changes:
                            if ch not in existing_parts:
                                existing_parts.append(ch)
                        recent_log.sudo().write({
                            'name': record.name,
                            'details': "; ".join(existing_parts),
                            'date': fields.Datetime.now(),
                        })
                    else:
                        self.env['dms.file.log'].sudo().create({
                            'name': record.name,
                            'file_id': record.id,
                            'action': 'edit',
                            'details': "; ".join(changes),
                            'user_id': self.env.user.id,
                            'date': fields.Datetime.now(),
                        })

            if has_new_content and record.content:
                if not record.revision_ids:
                    record.env['dms.file.revision'].sudo().create({
                        'file_id': record.id,
                        'version': '1.0',
                        'content': record.content,
                        'file_name': record.name,
                        'comments': _('Initial version'),
                        'is_current': False,
                    })

                record.revision_ids.sudo().write({'is_current': False})
                next_ver = f"1.{len(record.revision_ids)}"
                uploader = self.env.user if not self.env.user._is_public() else (record.document_owner_id or record.create_uid or self.env.ref('base.user_admin'))
                
                comment = self.env.context.get('revision_comment') or _('File updated / replaced')
                new_rev = record.env['dms.file.revision'].sudo().create({
                    'file_id': record.id,
                    'version': next_ver,
                    'content': record.content,
                    'file_name': vals.get('name') or record.name,
                    'uploader_id': uploader.id if uploader else False,
                    'upload_date': fields.Datetime.now(),
                    'comments': comment,
                    'is_current': True,
                })
                record.with_context(from_revert_revision=True, dms_skip_log=True).write({
                    'current_revision_id': new_rev.id
                })
        return res

    def action_open_move_wizard(self):
        for record in self:
            if record.is_locked:
                raise UserError(_("Cannot move '%s' because it is locked by %s. Please unlock it first.") % (record.name, record.locked_by.name or 'another user'))
        return {
            'name': _('Move File(s)'),
            'type': 'ir.actions.act_window',
            'res_model': 'dms.move.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'dms.file',
                'active_ids': self.ids,
            },
        }

    def action_send_to_trash(self):
        for record in self:
            if record.is_locked:
                raise UserError(_("Cannot send '%s' to Trash because it is locked by %s. Please unlock it first.") % (record.name, record.locked_by.name or 'another user'))
            record.write({
                'is_trashed': True,
                'trash_date': fields.Datetime.now(),
                'active': False
            })
        self.mapped('directory_id').invalidate_recordset(['count_files'])
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_restore(self):
        for record in self:
            record.write({
                'is_trashed': False,
                'trash_date': False,
                'active': True
            })
        self.mapped('directory_id').invalidate_recordset(['count_files'])
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def unlink(self):
        for record in self:
            if record.is_locked:
                raise UserError(_("Cannot delete '%s' because it is locked by %s. Please unlock it first.") % (record.name, record.locked_by.name or 'another user'))

        # Soft delete logic: if not in trash, send to trash instead.
        to_trash = self.filtered(lambda r: not r.is_trashed)
        if to_trash:
            to_trash.action_send_to_trash()

        to_delete = self - to_trash
        if to_delete:
            dirs = to_delete.mapped('directory_id')
            for record in to_delete:
                self.env['dms.file.log'].sudo().create({
                    'name': record.name,
                    'file_id': False,
                    'action': 'delete',
                    'details': _("Document permanently deleted"),
                    'user_id': self.env.user.id,
                    'date': fields.Datetime.now(),
                })
            res = super(DMSFile, to_delete).unlink()
            dirs.invalidate_recordset(['count_files'])
            return res
        return True

    @api.model
    def _cron_empty_trash(self):
        # Get retention delay from settings, default to 30 days
        delay_days = int(self.env["ir.config_parameter"].sudo().get_param("dms_enterprise.trash_delay", 30))
        if delay_days < 0:
            return # Disabled
            
        from dateutil.relativedelta import relativedelta
        cutoff_date = fields.Datetime.now() - relativedelta(days=delay_days)
        
        expired_files = self.search([
            ('is_trashed', '=', True),
            ('trash_date', '<', cutoff_date)
        ])
        if expired_files:
            expired_files.unlink()
            
        expired_dirs = self.env['dms.directory'].search([
            ('is_trashed', '=', True),
            ('trash_date', '<', cutoff_date)
        ])
        if expired_dirs:
            expired_dirs.unlink()

    @api.model
    def _cron_process_expiries(self):
        today = fields.Date.context_today(self)
        
        # 1. Process Trashing
        # Files where expiry_date <= today and not yet trashed
        expired_files = self.search([
            ('expiry_date', '!=', False),
            ('expiry_date', '<=', today),
            ('is_trashed', '=', False)
        ])
        if expired_files:
            expired_files.action_send_to_trash()

        # 2. Process Notifications
        # Files that have an expiry_date, are not trashed, haven't been notified yet, and have a notify_user_id
        pending_notifications = self.search([
            ('expiry_date', '!=', False),
            ('is_trashed', '=', False),
            ('notify_user_id', '!=', False),
            ('expiry_notification_sent', '=', False)
        ])
        
        from datetime import timedelta
        for file in pending_notifications:
            notify_date = file.expiry_date - timedelta(days=file.notify_before_days or 0)
            if today >= notify_date:
                # Create a Next Activity (To-Do) for the user
                self.env['mail.activity'].create({
                    'res_id': file.id,
                    'res_model_id': self.env['ir.model']._get('dms.file').id,
                    'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                    'summary': _('Document Expiry Warning'),
                    'note': _('This document will expire on %s and will be moved to the Trash automatically.', file.expiry_date),
                    'user_id': file.notify_user_id.id,
                    'date_deadline': file.expiry_date,
                })
                file.write({'expiry_notification_sent': True})

    def action_open_form_view(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'dms.file',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_setup_signatures(self):
        revision_ids = []
        for record in self:
            if record.is_locked and not record.is_lock_editor and not self.env.user.has_group('dms.group_dms_manager') and not self.env.su:
                raise UserError(_("Cannot setup signatures because '%s' is locked by %s.") % (record.name, record.locked_by.name or 'another user'))
            if record.mimetype and record.mimetype.startswith('image/'):
                raise UserError(_("Electronic signature is only supported for PDF documents. '%s' is an image.") % record.name)
            if record.mimetype and record.mimetype != 'application/pdf' and not record.name.lower().endswith('.pdf'):
                raise UserError(_("Electronic signature is only supported for PDF documents. '%s' is not a PDF.") % record.name)

            if not record.current_revision_id and record.content:
                revision = self.env['dms.file.revision'].create({
                    'file_id': record.id,
                    'version': '1.0',
                    'content': record.content,
                    'file_name': record.name,
                    'comments': 'Initial revision auto-created for signature setup.'
                })
                record.current_revision_id = revision.id
                
            if record.current_revision_id and record.current_revision_id.content:
                revision_ids.append(str(record.current_revision_id.id))
        
        if not revision_ids:
            raise UserError(_("Please upload a PDF document before setting up signatures."))
        
        return {
            'type': 'ir.actions.client',
            'tag': 'dms_signature_pdf_viewer',
            'target': 'current',
            'context': {
                'default_revision_ids': ','.join(revision_ids),
                'default_file_id': self.id,
            }
        }

    def action_open_properties(self):
        self.ensure_one()
        return {
            'name': _("Properties — %s") % (self.name or ''),
            'type': 'ir.actions.act_window',
            'res_model': 'dms.file',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('dms_enterprise_features.view_dms_file_properties_form').id, 'form')],
            'target': 'new',
            'flags': {'mode': 'readonly'},
        }

    def toggle_active(self):
        """Toggle active/archived state for selected records."""
        to_archive = self.filtered(lambda r: r.active)
        to_unarchive = self.filtered(lambda r: not r.active)
        if to_archive:
            to_archive.action_archive()
        if to_unarchive:
            to_unarchive.action_unarchive()
        return True



