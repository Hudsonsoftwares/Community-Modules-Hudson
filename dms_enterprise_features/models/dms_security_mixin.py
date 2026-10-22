from odoo import models, api, fields
from odoo.tools import SQL


class DmsSecurityMixin(models.AbstractModel):
    _inherit = "dms.security.mixin"

    @api.model
    def _get_access_groups_query(self, operation):
        """Return the query to select accessible directories based on custom folder permissions."""
        operation_check = {
            "create": "AND dp.perm_upload = TRUE",
            "read": "AND (dp.perm_view = TRUE OR dp.perm_download = TRUE)",
            "unlink": "AND dp.perm_delete = TRUE",
            "write": "AND (dp.perm_edit = TRUE OR dp.perm_move = TRUE OR dp.perm_rename = TRUE)",
        }[operation]

        uid = self.env.uid
        partner_id = self.env.user.partner_id.id if self.env.user.partner_id else 0

        select = (
            "("
            " SELECT dir_perm_rel.dir_id as aid"
            " FROM dms_dir_complete_perm_rel AS dir_perm_rel"
            " INNER JOIN dms_directory_permission AS dp ON dir_perm_rel.perm_id = dp.id"
            " LEFT JOIN dms_access_group AS dag ON dp.group_id = dag.id"
            " LEFT JOIN dms_access_group_users_rel AS users ON users.gid = dag.id"
            " WHERE (users.uid = %s OR dp.user_id = %s OR dp.partner_id = %s)"
            f" {operation_check}"
            ")"
        )
        return SQL(select, uid, uid, partner_id)

    permission_view = fields.Boolean(compute="_compute_granular_permissions", search="_search_permission_view")
    permission_download = fields.Boolean(compute="_compute_granular_permissions", search="_search_permission_download")
    permission_upload = fields.Boolean(compute="_compute_granular_permissions", search="_search_permission_upload")
    permission_edit = fields.Boolean(compute="_compute_granular_permissions", search="_search_permission_edit")
    permission_move = fields.Boolean(compute="_compute_granular_permissions", search="_search_permission_move")
    permission_rename = fields.Boolean(compute="_compute_granular_permissions", search="_search_permission_rename")
    permission_delete = fields.Boolean(compute="_compute_granular_permissions", search="_search_permission_delete")
    permission_share = fields.Boolean(compute="_compute_granular_permissions", search="_search_permission_share")

    @api.model
    def _search_permission_upload(self, operator, value):
        return self._get_permission_domain(operator, value, "create")

    @api.model
    def _search_permission_view(self, operator, value):
        return self._get_permission_domain(operator, value, "read")

    @api.model
    def _search_permission_download(self, operator, value):
        return self._get_permission_domain(operator, value, "read")

    @api.model
    def _search_permission_edit(self, operator, value):
        return self._get_permission_domain(operator, value, "write")

    @api.model
    def _search_permission_move(self, operator, value):
        return self._get_permission_domain(operator, value, "write")

    @api.model
    def _search_permission_rename(self, operator, value):
        return self._get_permission_domain(operator, value, "write")

    @api.model
    def _search_permission_delete(self, operator, value):
        return self._get_permission_domain(operator, value, "unlink")

    @api.model
    def _search_permission_share(self, operator, value):
        return self._get_permission_domain(operator, value, "read")

    @api.model
    def _get_domain_by_inheritance(self, operation):
        """Get domain for inherited accessible records (attachment-storage)."""
        from odoo.fields import Domain
        OR = Domain.OR
        FALSE_DOMAIN = [(0, '=', 1)]
        from odoo.exceptions import AccessError

        inherited_access_field = "storage_id_inherit_access_from_parent_record"
        if self._name != "dms.directory":
            inherited_access_field = f"{self._directory_field}.{inherited_access_field}"
        inherited_access_domain = [
            ("storage_id_save_type", "=", "attachment"),
            (inherited_access_field, "=", True),
        ]
        domains = []
        related_groups = self.sudo().read_group(
            domain=inherited_access_domain + [("res_model", "!=", False)],
            fields=["res_id:array_agg"],
            groupby=["res_model"],
        )
        for group in related_groups:
            try:
                model = self.env[group["res_model"]]
            except KeyError:
                continue
            try:
                model.check_access(operation)
            except AccessError:
                continue
            domains.append([("res_model", "=", model._name), ("res_id", "=", False)])
            res_ids = [i for i in group["res_id"] if i]
            model_records = model.browse(res_ids).exists()
            related_ok = model_records._filtered_access(operation)
            if not related_ok:
                continue
            domains.append(
                [("res_model", "=", model._name), ("res_id", "in", related_ok.ids)]
            )
        if not domains:
            return FALSE_DOMAIN
        return inherited_access_domain + OR(domains)

    @api.model
    def _is_dms_privileged_user(self):
        """Return True if the current user should have unrestricted DMS access."""
        return (
            self.env.is_superuser()
            or self.env.user.has_group('dms.group_dms_manager')
            or self.env.user.has_group('base.group_system')
            or self.env.user.has_group('dms_enterprise_features.group_dms_administrator')
        )

    @api.model
    def _get_permission_domain(self, operator, value, operation):
        """
        Central security domain used by the ir.access domain_force expressions.

        Security model:
          - DMS Managers / Administrators / Superuser -> unrestricted access.
          - All other users -> only records explicitly assigned or owned by them.
        """
        from odoo.fields import Domain
        OR = Domain.OR
        AND = Domain.AND
        TRUE_DOMAIN = [(1, '=', 1)]
        FALSE_DOMAIN = [(0, '=', 1)]
        NEGATIVE_TERM_OPERATORS = ('!=', 'not like', 'not ilike', 'not in', 'not any', 'not any!')

        positive = (operator not in NEGATIVE_TERM_OPERATORS) == bool(value)

        if self._is_dms_privileged_user():
            return TRUE_DOMAIN if positive else FALSE_DOMAIN

        uid = self.env.uid
        partner_id = self.env.user.partner_id.id if self.env.user.partner_id else 0

        # Collect user's group IDs and department IDs for file-level access checks
        user_group_ids = self.env['res.groups'].sudo().search([('user_ids', '=', uid)]).ids
        user_groups = tuple(user_group_ids) if user_group_ids else (0,)
        dept_ids = []
        if hasattr(self.env.user, 'employee_ids'):
            dept_ids = self.env.user.sudo().employee_ids.mapped('department_id').ids
        user_depts = tuple(dept_ids) if dept_ids else (0,)

        if self._name == 'dms.directory':
            result = self._build_directory_domain(
                operation, uid, partner_id, user_groups, user_depts, OR, AND
            )
        elif self._name == 'dms.file':
            result = self._build_file_domain(
                operation, uid, partner_id, user_groups, user_depts, OR, AND,
                FALSE_DOMAIN
            )
        else:
            # Fallback for any other DMS model
            result = OR([
                self._get_domain_by_access_groups(operation),
                self._get_domain_by_inheritance(operation),
            ])

        if not positive:
            result.insert(0, "!")
        return result

    @api.model
    def _build_directory_domain(
        self, operation, uid, partner_id, user_groups, user_depts, OR, AND
    ):
        """
        Security domain for dms.directory.

        Read access:
          (1) User has an explicit directory permission line granting view/download.
          (2) Directory is an ancestor of a dir/file the user can reach (navigation).
        Write/Create/Unlink:
          Only explicit directory permission lines grant those rights.
        """
        # Rule 1: directories with matching permission entry for this user
        dir_perm_domain = [
            ('storage_id_inherit_access_from_parent_record', '=', False),
            ('id', 'in', self._get_access_groups_query(operation)),
        ]

        if operation != 'read':
            return dir_perm_domain

        # Rule 2 (read only): ancestor directories for tree navigation
        # Walk up the tree from directories/files the user can directly access
        ancestor_sql = SQL(
            """
            WITH RECURSIVE accessible AS (

                -- Directories with explicit view/download permission for this user
                SELECT rel.dir_id AS id
                FROM dms_dir_complete_perm_rel rel
                INNER JOIN dms_directory_permission dp ON rel.perm_id = dp.id
                LEFT JOIN dms_access_group dag ON dp.group_id = dag.id
                LEFT JOIN dms_access_group_users_rel gu ON gu.gid = dag.id
                WHERE (gu.uid = %s OR dp.user_id = %s OR dp.partner_id = %s)
                  AND (dp.perm_view = TRUE OR dp.perm_download = TRUE)

                UNION

                -- Directories containing files this user can access
                SELECT DISTINCT f.directory_id AS id
                FROM dms_file f
                LEFT JOIN dms_file_access fa ON fa.file_id = f.id
                WHERE f.directory_id IS NOT NULL
                  AND f.active = TRUE
                  AND (
                      f.document_owner_id = %s
                      OR f.create_uid = %s
                      OR (
                          (fa.user_id = %s OR fa.partner_id = %s
                           OR fa.group_id IN %s OR fa.department_id IN %s)
                          AND (fa.perm_view = TRUE OR fa.perm_download = TRUE
                               OR fa.perm_share = TRUE)
                      )
                  )
            ),
            ancestors AS (
                SELECT id FROM accessible
                UNION
                SELECT d.parent_id
                FROM dms_directory d
                INNER JOIN ancestors a ON d.id = a.id
                WHERE d.parent_id IS NOT NULL
            )
            SELECT id FROM ancestors WHERE id IS NOT NULL
            """,
            uid, uid, partner_id,          # permission line match
            uid, uid,                      # owner / creator of file
            uid, partner_id, user_groups, user_depts  # file access entry
        )

        return OR([dir_perm_domain, [('id', 'in', ancestor_sql)]])

    @api.model
    def _build_file_domain(
        self, operation, uid, partner_id, user_groups, user_depts, OR, AND,
        FALSE_DOMAIN
    ):
        """
        Security domain for dms.file.

        A file is accessible when ANY of:
          (1) Explicit dms_file_access entry grants the required operation.
          (2) User is the owner/creator:
              - Read: always visible.
              - Write/Unlink: only if directory permits OR directory is unrestricted.
          (3) [Read only] User is listed as an approver.
          (4) File has no file-level access rules AND the directory explicitly
              grants the user the required operation.
        """
        op_file_sql = {
            'read':   '(fa.perm_view = TRUE OR fa.perm_download = TRUE OR fa.perm_share = TRUE)',
            'write':  '(fa.perm_edit = TRUE OR fa.perm_move = TRUE OR fa.perm_rename = TRUE)',
            'unlink': 'fa.perm_delete = TRUE',
            'create': 'FALSE',
        }.get(operation, 'FALSE')

        op_dir_sql = {
            'read':   '(dp.perm_view = TRUE OR dp.perm_download = TRUE)',
            'write':  '(dp.perm_edit = TRUE OR dp.perm_move = TRUE OR dp.perm_rename = TRUE)',
            'unlink': 'dp.perm_delete = TRUE',
            'create': 'dp.perm_upload = TRUE',
        }.get(operation, 'FALSE')

        domains = []

        # Rule 1: explicit file-level access entry
        if operation != 'create':
            domains.append([('id', 'in', SQL(
                "SELECT fa.file_id FROM dms_file_access fa"
                " WHERE (fa.user_id = %s OR fa.partner_id = %s"
                "        OR fa.group_id IN %s OR fa.department_id IN %s)"
                " AND " + op_file_sql,
                uid, partner_id, user_groups, user_depts
            ))])

        # Rule 2: owner / creator
        if operation == 'read':
            # Owners can always read their own files
            domains.append([('document_owner_id', '=', uid)])
            domains.append([('create_uid', '=', uid)])

        elif operation in ('write', 'unlink'):
            # Owners can edit/delete their files only when:
            # - the directory explicitly grants write/delete, OR
            # - the directory has NO restriction at all (open folder)
            domains.append([('id', 'in', SQL(
                "SELECT f.id FROM dms_file f"
                " WHERE (f.document_owner_id = %s OR f.create_uid = %s)"
                "   AND ("
                "       EXISTS ("
                "           SELECT 1 FROM dms_dir_complete_perm_rel rel"
                "           INNER JOIN dms_directory_permission dp ON rel.perm_id = dp.id"
                "           LEFT JOIN dms_access_group dag ON dp.group_id = dag.id"
                "           LEFT JOIN dms_access_group_users_rel gu ON gu.gid = dag.id"
                "           WHERE rel.dir_id = f.directory_id"
                "             AND (gu.uid = %s OR dp.user_id = %s OR dp.partner_id = %s)"
                "             AND " + op_dir_sql +
                "       ) OR NOT EXISTS ("
                "           SELECT 1 FROM dms_dir_complete_perm_rel"
                "           WHERE dir_id = f.directory_id"
                "       )"
                "   )",
                uid, uid, uid, uid, partner_id
            ))])

        # Rule 3: approver (read only)
        if operation == 'read':
            domains.append([('id', 'in', SQL(
                "SELECT DISTINCT ap.file_id FROM dms_file_approval ap"
                " WHERE ap.approver_id = %s",
                uid
            ))])

        # Rule 4: no file-level rules + directory grants this operation
        if operation in ('read', 'write', 'unlink'):
            domains.append([('id', 'in', SQL(
                "SELECT f.id FROM dms_file f"
                " WHERE NOT EXISTS ("
                "     SELECT 1 FROM dms_file_access WHERE file_id = f.id"
                " )"
                " AND EXISTS ("
                "     SELECT 1 FROM dms_dir_complete_perm_rel rel"
                "     INNER JOIN dms_directory_permission dp ON rel.perm_id = dp.id"
                "     LEFT JOIN dms_access_group dag ON dp.group_id = dag.id"
                "     LEFT JOIN dms_access_group_users_rel gu ON gu.gid = dag.id"
                "     WHERE rel.dir_id = f.directory_id"
                "       AND (gu.uid = %s OR dp.user_id = %s OR dp.partner_id = %s)"
                "       AND " + op_dir_sql +
                " )",
                uid, uid, partner_id
            ))])

        return OR(domains) if domains else FALSE_DOMAIN

    def _compute_permissions(self):
        for record in self:
            if (self.env.su
                    or self.env.user.has_group('dms.group_dms_manager')
                    or self.env.user.has_group('base.group_system')
                    or self.env.user.has_group('dms_enterprise_features.group_dms_administrator')):
                record.permission_read = True
                record.permission_create = True
                record.permission_write = True
                record.permission_unlink = True
            else:
                record.permission_read = record.permission_view or record.permission_download
                record.permission_create = record.permission_upload
                record.permission_write = record.permission_edit or record.permission_move or record.permission_rename
                record.permission_unlink = record.permission_delete

    def _compute_granular_permissions(self):  # noqa: C901
        for record in self:
            if (self.env.su
                    or self.env.user.has_group('dms.group_dms_manager')
                    or self.env.user.has_group('base.group_system')
                    or self.env.user.has_group('dms_enterprise_features.group_dms_administrator')):
                record.permission_view = True
                record.permission_download = True
                record.permission_upload = True
                record.permission_edit = True
                record.permission_move = True
                record.permission_rename = True
                record.permission_delete = True
                record.permission_share = True
                continue

            directory = False
            if record._name == "dms.directory":
                directory = record
            elif hasattr(record, "directory_id") and record.directory_id:
                directory = record.directory_id

            dir_perms = {
                'view': False, 'download': False, 'upload': False,
                'edit': False, 'move': False, 'rename': False,
                'delete': False, 'share': False,
            }

            if directory:
                uid = self.env.user.id
                partner_id = self.env.user.partner_id.id if self.env.user.partner_id else 0
                for perm in directory.sudo().complete_permission_line_ids:
                    applies = False
                    if perm.group_id and self.env.user in perm.group_id.users:
                        applies = True
                    elif perm.user_id and perm.user_id.id == uid:
                        applies = True
                    elif perm.partner_id and perm.partner_id.id == partner_id:
                        applies = True
                    if applies:
                        if perm.perm_view:     dir_perms['view'] = True
                        if perm.perm_download: dir_perms['download'] = True
                        if perm.perm_upload:   dir_perms['upload'] = True
                        if perm.perm_edit:     dir_perms['edit'] = True
                        if perm.perm_move:     dir_perms['move'] = True
                        if perm.perm_rename:   dir_perms['rename'] = True
                        if perm.perm_delete:   dir_perms['delete'] = True
                        if perm.perm_share:    dir_perms['share'] = True

            if record._name == "dms.file":
                is_owner = (
                    (record.document_owner_id and record.document_owner_id.id == self.env.user.id)
                    or (record.create_uid and record.create_uid.id == self.env.user.id)
                )
                is_approver = self.env.user.id in record.sudo().approval_ids.mapped('approver_id.id')
                partner_id = self.env.user.partner_id.id if self.env.user.partner_id else 0

                access_records = record.sudo().access_ids if hasattr(record, "access_ids") else []
                if access_records:
                    user_dept_ids = []
                    if hasattr(self.env.user, "employee_ids"):
                        user_dept_ids = self.env.user.sudo().employee_ids.mapped("department_id").ids

                    file_perms = {
                        'view': False, 'download': False,
                        'edit': False, 'move': False, 'rename': False,
                        'delete': False, 'share': False,
                    }
                    user_has_file_rule = False
                    for access in access_records:
                        applies = False
                        if access.user_id and access.user_id.id == self.env.user.id:
                            applies = True
                        elif access.partner_id and access.partner_id.id == partner_id:
                            applies = True
                        elif access.group_id and self.env.user in access.group_id.user_ids:
                            applies = True
                        elif access.department_id and access.department_id.id in user_dept_ids:
                            applies = True
                        if applies:
                            user_has_file_rule = True
                            if access.perm_view:     file_perms['view'] = True
                            if access.perm_download: file_perms['download'] = True
                            if access.perm_edit:     file_perms['edit'] = True
                            if access.perm_move:     file_perms['move'] = True
                            if access.perm_rename:   file_perms['rename'] = True
                            if access.perm_delete:   file_perms['delete'] = True
                            if access.perm_share:    file_perms['share'] = True

                    if user_has_file_rule:
                        record.permission_view     = file_perms['view'] or is_approver
                        record.permission_download = file_perms['download'] or is_approver
                        record.permission_upload   = False
                        record.permission_edit     = file_perms['edit']
                        record.permission_move     = file_perms['move']
                        record.permission_rename   = file_perms['rename']
                        record.permission_delete   = file_perms['delete']
                        record.permission_share    = file_perms['share']
                    elif is_owner:
                        record.permission_view = record.permission_download = True
                        record.permission_upload = False
                        record.permission_edit = record.permission_move = True
                        record.permission_rename = record.permission_delete = True
                        record.permission_share = True
                    elif is_approver:
                        record.permission_view = record.permission_download = True
                        record.permission_upload = False
                        record.permission_edit = record.permission_move = False
                        record.permission_rename = record.permission_delete = False
                        record.permission_share = False
                    else:
                        # File has explicit rules but user has no entry -> DENY all
                        record.permission_view = record.permission_download = False
                        record.permission_upload = record.permission_edit = False
                        record.permission_move = record.permission_rename = False
                        record.permission_delete = record.permission_share = False
                else:
                    # No file-level rules -> inherit directory perms + owner override
                    if is_owner:
                        record.permission_view = record.permission_download = True
                        record.permission_upload = dir_perms['upload']
                        record.permission_edit = record.permission_move = True
                        record.permission_rename = record.permission_delete = True
                        record.permission_share = True
                    elif is_approver:
                        record.permission_view = record.permission_download = True
                        record.permission_upload = dir_perms['upload']
                        record.permission_edit = dir_perms['edit']
                        record.permission_move = dir_perms['move']
                        record.permission_rename = dir_perms['rename']
                        record.permission_delete = dir_perms['delete']
                        record.permission_share = dir_perms['share']
                    else:
                        record.permission_view     = dir_perms['view']
                        record.permission_download = dir_perms['download']
                        record.permission_upload   = dir_perms['upload']
                        record.permission_edit     = dir_perms['edit']
                        record.permission_move     = dir_perms['move']
                        record.permission_rename   = dir_perms['rename']
                        record.permission_delete   = dir_perms['delete']
                        record.permission_share    = dir_perms['share']
            else:
                # Directory record
                record.permission_view     = dir_perms['view']
                record.permission_download = dir_perms['download']
                record.permission_upload   = dir_perms['upload']
                record.permission_edit     = dir_perms['edit']
                record.permission_move     = dir_perms['move']
                record.permission_rename   = dir_perms['rename']
                record.permission_delete   = dir_perms['delete']
                record.permission_share    = dir_perms['share']