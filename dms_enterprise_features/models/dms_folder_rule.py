# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class DmsFolderRule(models.Model):
    """Auto-assignment rule that routes documents from a business model
    to a specific DMS directory automatically.

    Rules are evaluated in sequence order (lowest first). The first matching
    rule wins and routes the document to its configured directory.
    """

    _name = "dms.folder.rule"
    _description = "DMS Folder Auto-Assignment Rule"
    _order = "sequence asc, name asc"

    name = fields.Char(
        string="Rule Name",
        required=True,
        help="Descriptive name for this auto-assignment rule.",
    )
    active = fields.Boolean(
        default=True,
        help="Inactive rules are not evaluated during auto-assignment.",
    )
    sequence = fields.Integer(
        default=10,
        help="Rules are evaluated in ascending sequence order. "
             "The first matching rule wins.",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
        help="If set, this rule only applies to attachments from the given company.",
    )

    # ── Source Model ─────────────────────────────────────────────────────────
    model_id = fields.Many2one(
        comodel_name="ir.model",
        string="Apply On Model",
        required=True,
        ondelete="cascade",
        help="Odoo model whose attachments will be automatically routed.",
    )
    model_name = fields.Char(
        related="model_id.model",
        string="Model Technical Name",
        store=True,
        readonly=True,
    )
    domain = fields.Char(
        string="Filter Domain",
        default="[]",
        help="Optional domain expression to further filter which records "
             "trigger this rule. Example: [('state','=','done')]",
    )

    # ── Target Directory ─────────────────────────────────────────────────────
    directory_id = fields.Many2one(
        comodel_name="dms.directory",
        string="Target Folder",
        required=True,
        ondelete="restrict",
        help="DMS folder where matched documents will be routed.",
    )
    tag_ids = fields.Many2many(
        comodel_name="dms.tag",
        relation="dms_folder_rule_tag_rel",
        column1="rule_id",
        column2="tag_id",
        string="Default Tags",
        help="Tags automatically applied to documents routed by this rule.",
    )

    # ── Sub-folder Options ────────────────────────────────────────────────────
    create_subfolder = fields.Boolean(
        string="Create Per-Record Subfolder",
        default=False,
        help="When enabled, a subfolder named after the record is created "
             "inside the target folder. Each record gets its own subfolder.",
    )
    subfolder_name_field = fields.Many2one(
        comodel_name="ir.model.fields",
        string="Subfolder Name Field",
        domain="[('model_id', '=', model_id), ('ttype', 'in', ['char','name','text'])]",
        help="Field from the source record used as the subfolder name. "
             "Defaults to display_name if not set.",
    )

    # ── Business Area Label (for config settings grouping) ───────────────────
    area = fields.Selection(
        selection=[
            ("hr", "Human Resources"),
            ("recruitment", "Recruitment"),
            ("accounting", "Accounting"),
            ("product", "Products"),
            ("project", "Projects"),
            ("approvals", "Approvals"),
            ("sign", "Sign"),
            ("fleet", "Fleet"),
            ("other", "Other"),
        ],
        string="Business Area",
        default="other",
        help="Business area this rule belongs to. Used to group rules in the "
             "settings panel.",
    )

    # ── Computed ──────────────────────────────────────────────────────────────
    directory_path = fields.Char(
        related="directory_id.complete_name",
        string="Target Folder Path",
        readonly=True,
    )

    # ── Actions ───────────────────────────────────────────────────────────────
    def action_open_directory(self):
        """Navigate to the target directory."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.directory_id.name,
            "res_model": "dms.directory",
            "res_id": self.directory_id.id,
            "view_mode": "form",
            "target": "current",
        }

    # ── Business Logic ────────────────────────────────────────────────────────
    def _evaluate_domain(self, record):
        """Return True if the record matches the rule's domain filter."""
        if not self.domain or self.domain.strip() == "[]":
            return True
        try:
            import ast
            domain = ast.literal_eval(self.domain)
            return bool(self.env[self.model_name].search(
                [("id", "=", record.id)] + domain, limit=1
            ))
        except Exception:
            _logger.warning(
                "DMS Folder Rule '%s': could not evaluate domain '%s'",
                self.name,
                self.domain,
            )
            return True

    def _get_or_create_subfolder(self, record, parent_directory):
        """Find or create a per-record subfolder inside parent_directory."""
        # Determine subfolder name
        if self.subfolder_name_field:
            field_name = self.subfolder_name_field.name
            subfolder_name = str(record[field_name] or record.display_name or "Unknown")
        else:
            subfolder_name = record.display_name or str(record.id)

        # Sanitise the name (max 255 chars, no slashes)
        subfolder_name = subfolder_name[:255].replace("/", "-").strip()

        # Look for existing subfolder
        existing = self.env["dms.directory"].sudo().search([
            ("parent_id", "=", parent_directory.id),
            ("name", "=", subfolder_name),
        ], limit=1)
        if existing:
            return existing

        # Create new subfolder
        return self.env["dms.directory"].sudo().with_context(check_name=False).create({
            "name": subfolder_name,
            "parent_id": parent_directory.id,
            "storage_id": parent_directory.storage_id.id,
        })

    @api.model
    def find_matching_rule(self, res_model, record=None):
        """Return the first active rule matching the given model (and record).

        Args:
            res_model (str): Odoo model technical name, e.g. 'hr.employee'
            record: optional browse record for domain evaluation
        Returns:
            dms.folder.rule or empty recordset
        """
        rules = self.sudo().search([
            ("model_name", "=", res_model),
            ("active", "=", True),
        ])
        for rule in rules:
            if record is None or rule._evaluate_domain(record):
                return rule
        return self.browse()

    def route_attachment(self, attachment):
        """Route a single ir.attachment to the DMS directory configured in
        this rule. Creates a dms.file and optionally a per-record subfolder.

        Args:
            attachment: ir.attachment record
        Returns:
            dms.file record or False
        """
        self.ensure_one()
        if not attachment.res_model or not attachment.res_id:
            return False

        target_dir = self.directory_id

        # Per-record subfolder
        if self.create_subfolder:
            try:
                record = self.env[attachment.res_model].sudo().browse(attachment.res_id)
                if record.exists():
                    target_dir = self._get_or_create_subfolder(record, target_dir)
            except Exception as e:
                _logger.warning("DMS Folder Rule: could not create subfolder: %s", e)

        # Check if a DMS file already exists for this attachment
        existing_file = self.env["dms.file"].sudo().search([
            ("attachment_id", "=", attachment.id),
            ("directory_id", "=", target_dir.id),
        ], limit=1)
        if existing_file:
            return existing_file

        # Create the DMS file
        try:
            dms_file = self.env["dms.file"].sudo().create({
                "name": attachment.name,
                "directory_id": target_dir.id,
                "attachment_id": attachment.id,
                "res_model": attachment.res_model,
                "res_id": attachment.res_id,
                "tag_ids": [(6, 0, self.tag_ids.ids)] if self.tag_ids else False,
            })
            _logger.info(
                "DMS: Routed attachment '%s' (id=%s) → folder '%s' via rule '%s'",
                attachment.name, attachment.id, target_dir.complete_name, self.name,
            )
            return dms_file
        except Exception as e:
            _logger.warning(
                "DMS Folder Rule '%s': failed to create dms.file for attachment %s: %s",
                self.name, attachment.id, e,
            )
            return False

    # ── Constraints ───────────────────────────────────────────────────────────
    @api.constrains("domain")
    def _check_domain(self):
        import ast
        for rule in self:
            if rule.domain and rule.domain.strip() != "[]":
                try:
                    ast.literal_eval(rule.domain)
                except (ValueError, SyntaxError):
                    raise ValidationError(
                        _(
                            "Rule '%(name)s': domain '%(domain)s' is not a valid "
                            "Python expression.",
                            name=rule.name,
                            domain=rule.domain,
                        )
                    )
