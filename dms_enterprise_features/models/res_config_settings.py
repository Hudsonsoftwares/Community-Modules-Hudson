# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Area → (model name, display label)
_AREA_MODELS = {
    "hr": ("hr.employee", "Human Resources"),
    "recruitment": ("hr.applicant", "Recruitment"),
    "accounting": ("account.move", "Accounting"),
    "product": ("product.template", "Products"),
    "project": ("project.project", "Projects"),
    "approvals": ("approval.request", "Approvals"),
    "sign": ("sign.request", "Sign"),
}


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # ── Trash Management ──────────────────────────────────────────────────────
    documents_trash_delay = fields.Integer(
        string="Deletion Delay (days)",
        config_parameter="dms_enterprise.trash_delay",
        default=30,
        help="Number of days before documents in the Trash are permanently deleted.",
    )

    # ── Projects ──────────────────────────────────────────────────────────────
    documents_project_enabled = fields.Boolean(
        string="Projects",
        config_parameter="dms_enterprise.project_enabled",
        help="Centralize files attached to projects.",
    )
    documents_project_folder_id = fields.Many2one(
        comodel_name="dms.directory",
        string="Projects Folder",
        compute="_compute_project_folder_id",
        inverse="_set_project_folder_id",
        help="Default DMS folder for project documents.",
    )

    # ── Products ──────────────────────────────────────────────────────────────
    documents_product_enabled = fields.Boolean(
        string="Product",
        config_parameter="dms_enterprise.product_enabled",
        help="Centralize files attached to products.",
    )
    documents_product_folder_id = fields.Many2one(
        comodel_name="dms.directory",
        string="Products Folder",
        compute="_compute_product_folder_id",
        inverse="_set_product_folder_id",
        help="Default DMS folder for product documents.",
    )
    documents_product_tag_ids = fields.Many2many(
        comodel_name="dms.tag",
        relation="res_config_settings_product_tag_rel",
        string="Product Tags",
        compute="_compute_product_tag_ids",
        inverse="_set_product_tag_ids",
        help="Tags automatically applied to product documents.",
    )

    # ── Recruitment ───────────────────────────────────────────────────────────
    documents_recruitment_enabled = fields.Boolean(
        string="Recruitment",
        config_parameter="dms_enterprise.recruitment_enabled",
        help="Centralize files attached to applications and job positions.",
    )
    documents_recruitment_folder_id = fields.Many2one(
        comodel_name="dms.directory",
        string="Recruitment Folder",
        compute="_compute_recruitment_folder_id",
        inverse="_set_recruitment_folder_id",
    )
    documents_recruitment_tag_ids = fields.Many2many(
        comodel_name="dms.tag",
        relation="res_config_settings_recruitment_tag_rel",
        string="Recruitment Tags",
        compute="_compute_recruitment_tag_ids",
        inverse="_set_recruitment_tag_ids",
    )

    # ── Human Resources ───────────────────────────────────────────────────────
    documents_hr_enabled = fields.Boolean(
        string="Human Resources",
        config_parameter="dms_enterprise.hr_enabled",
        help="Centralize your employees' documents (contracts, payslips, etc.).",
    )
    documents_hr_folder_id = fields.Many2one(
        comodel_name="dms.directory",
        string="Employees Folder",
        compute="_compute_hr_folder_id",
        inverse="_set_hr_folder_id",
    )
    documents_hr_create_subfolders = fields.Boolean(
        string="Create Employee Subfolders",
        config_parameter="dms_enterprise.hr_create_subfolders",
        help="Automatically create a subfolder for each employee.",
    )
    documents_hr_contract_tag_ids = fields.Many2many(
        comodel_name="dms.tag",
        relation="res_config_settings_hr_contract_tag_rel",
        string="Contracts Tags",
        compute="_compute_hr_contract_tag_ids",
        inverse="_set_hr_contract_tag_ids",
        help="Default tags applied to contract documents.",
    )
    documents_hr_payslip_tag_ids = fields.Many2many(
        comodel_name="dms.tag",
        relation="res_config_settings_hr_payslip_tag_rel",
        string="Payslip Tags",
        compute="_compute_hr_payslip_tag_ids",
        inverse="_set_hr_payslip_tag_ids",
        help="Default tags applied to payslip documents.",
    )

    # ── Accounting ────────────────────────────────────────────────────────────
    documents_accounting_enabled = fields.Boolean(
        string="Accounting",
        config_parameter="dms_enterprise.accounting_enabled",
        help="Centralize accounting files and documents.",
    )
    documents_accounting_folder_id = fields.Many2one(
        comodel_name="dms.directory",
        string="Accounting Folder",
        compute="_compute_accounting_folder_id",
        inverse="_set_accounting_folder_id",
    )
    documents_accounting_tag_ids = fields.Many2many(
        comodel_name="dms.tag",
        relation="res_config_settings_accounting_tag_rel",
        string="Accounting Tags",
        compute="_compute_accounting_tag_ids",
        inverse="_set_accounting_tag_ids",
    )

    # ── Approvals ─────────────────────────────────────────────────────────────
    documents_approvals_enabled = fields.Boolean(
        string="Approvals",
        config_parameter="dms_enterprise.approvals_enabled",
        help="Centralize files attached to Approvals.",
    )
    documents_approvals_folder_id = fields.Many2one(
        comodel_name="dms.directory",
        string="Approvals Folder",
        compute="_compute_approvals_folder_id",
        inverse="_set_approvals_folder_id",
    )
    documents_approvals_tag_ids = fields.Many2many(
        comodel_name="dms.tag",
        relation="res_config_settings_approvals_tag_rel",
        string="Approvals Tags",
        compute="_compute_approvals_tag_ids",
        inverse="_set_approvals_tag_ids",
    )

    # ── Sign ──────────────────────────────────────────────────────────────────
    documents_sign_enabled = fields.Boolean(
        string="Sign",
        config_parameter="dms_enterprise.sign_enabled",
        help="Link Sign Templates to directories.",
    )
    documents_sign_folder_id = fields.Many2one(
        comodel_name="dms.directory",
        string="Sign Folder",
        compute="_compute_sign_folder_id",
        inverse="_set_sign_folder_id",
    )

    # ── Document Controller ───────────────────────────────────────────────────
    group_dms_document_controller = fields.Boolean(
        string="Document Controller Features",
        implied_group="dms_enterprise_features.group_dms_document_controller",
        help="Enable Document Controller features like revisions, approval workflows, and signature requests."
    )

    # ── Helpers: folder id stored as ir.config_parameter ─────────────────────
    def _get_folder_from_param(self, param_key):
        param = self.env["ir.config_parameter"].sudo().get_param(param_key)
        return self.env["dms.directory"].browse(int(param)) if param else False

    def _set_folder_to_param(self, param_key, folder_id):
        self.env["ir.config_parameter"].sudo().set_param(
            param_key, str(folder_id) if folder_id else ""
        )

    def _get_tags_from_param(self, param_key):
        param = self.env["ir.config_parameter"].sudo().get_param(param_key, "")
        ids = [int(i) for i in param.split(",") if i.strip().isdigit()]
        return self.env["dms.tag"].browse(ids)

    def _set_tags_to_param(self, param_key, tag_ids):
        self.env["ir.config_parameter"].sudo().set_param(
            param_key, ",".join(str(i) for i in tag_ids.ids)
        )

    # ── Compute / Inverse for each folder field ───────────────────────────────
    @api.depends_context("company")
    def _compute_project_folder_id(self):
        for rec in self:
            rec.documents_project_folder_id = rec._get_folder_from_param(
                "dms_enterprise.project_folder_id"
            )

    def _set_project_folder_id(self):
        for rec in self:
            rec._set_folder_to_param(
                "dms_enterprise.project_folder_id",
                rec.documents_project_folder_id.id,
            )
            rec._sync_rule("project", rec.documents_project_folder_id)

    @api.depends_context("company")
    def _compute_product_folder_id(self):
        for rec in self:
            rec.documents_product_folder_id = rec._get_folder_from_param(
                "dms_enterprise.product_folder_id"
            )

    def _set_product_folder_id(self):
        for rec in self:
            rec._set_folder_to_param(
                "dms_enterprise.product_folder_id",
                rec.documents_product_folder_id.id,
            )
            rec._sync_rule("product", rec.documents_product_folder_id)

    @api.depends_context("company")
    def _compute_product_tag_ids(self):
        for rec in self:
            rec.documents_product_tag_ids = rec._get_tags_from_param(
                "dms_enterprise.product_tag_ids"
            )

    def _set_product_tag_ids(self):
        for rec in self:
            rec._set_tags_to_param("dms_enterprise.product_tag_ids", rec.documents_product_tag_ids)

    @api.depends_context("company")
    def _compute_recruitment_folder_id(self):
        for rec in self:
            rec.documents_recruitment_folder_id = rec._get_folder_from_param(
                "dms_enterprise.recruitment_folder_id"
            )

    def _set_recruitment_folder_id(self):
        for rec in self:
            rec._set_folder_to_param(
                "dms_enterprise.recruitment_folder_id",
                rec.documents_recruitment_folder_id.id,
            )
            rec._sync_rule("recruitment", rec.documents_recruitment_folder_id)

    @api.depends_context("company")
    def _compute_recruitment_tag_ids(self):
        for rec in self:
            rec.documents_recruitment_tag_ids = rec._get_tags_from_param(
                "dms_enterprise.recruitment_tag_ids"
            )

    def _set_recruitment_tag_ids(self):
        for rec in self:
            rec._set_tags_to_param(
                "dms_enterprise.recruitment_tag_ids", rec.documents_recruitment_tag_ids
            )

    @api.depends_context("company")
    def _compute_hr_folder_id(self):
        for rec in self:
            rec.documents_hr_folder_id = rec._get_folder_from_param(
                "dms_enterprise.hr_folder_id"
            )

    def _set_hr_folder_id(self):
        for rec in self:
            rec._set_folder_to_param(
                "dms_enterprise.hr_folder_id", rec.documents_hr_folder_id.id
            )
            rec._sync_rule("hr", rec.documents_hr_folder_id)

    @api.depends_context("company")
    def _compute_hr_contract_tag_ids(self):
        for rec in self:
            rec.documents_hr_contract_tag_ids = rec._get_tags_from_param(
                "dms_enterprise.hr_contract_tag_ids"
            )

    def _set_hr_contract_tag_ids(self):
        for rec in self:
            rec._set_tags_to_param(
                "dms_enterprise.hr_contract_tag_ids", rec.documents_hr_contract_tag_ids
            )

    @api.depends_context("company")
    def _compute_hr_payslip_tag_ids(self):
        for rec in self:
            rec.documents_hr_payslip_tag_ids = rec._get_tags_from_param(
                "dms_enterprise.hr_payslip_tag_ids"
            )

    def _set_hr_payslip_tag_ids(self):
        for rec in self:
            rec._set_tags_to_param(
                "dms_enterprise.hr_payslip_tag_ids", rec.documents_hr_payslip_tag_ids
            )

    @api.depends_context("company")
    def _compute_accounting_folder_id(self):
        for rec in self:
            rec.documents_accounting_folder_id = rec._get_folder_from_param(
                "dms_enterprise.accounting_folder_id"
            )

    def _set_accounting_folder_id(self):
        for rec in self:
            rec._set_folder_to_param(
                "dms_enterprise.accounting_folder_id",
                rec.documents_accounting_folder_id.id,
            )
            rec._sync_rule("accounting", rec.documents_accounting_folder_id)

    @api.depends_context("company")
    def _compute_accounting_tag_ids(self):
        for rec in self:
            rec.documents_accounting_tag_ids = rec._get_tags_from_param(
                "dms_enterprise.accounting_tag_ids"
            )

    def _set_accounting_tag_ids(self):
        for rec in self:
            rec._set_tags_to_param(
                "dms_enterprise.accounting_tag_ids", rec.documents_accounting_tag_ids
            )

    @api.depends_context("company")
    def _compute_approvals_folder_id(self):
        for rec in self:
            rec.documents_approvals_folder_id = rec._get_folder_from_param(
                "dms_enterprise.approvals_folder_id"
            )

    def _set_approvals_folder_id(self):
        for rec in self:
            rec._set_folder_to_param(
                "dms_enterprise.approvals_folder_id",
                rec.documents_approvals_folder_id.id,
            )
            rec._sync_rule("approvals", rec.documents_approvals_folder_id)

    @api.depends_context("company")
    def _compute_approvals_tag_ids(self):
        for rec in self:
            rec.documents_approvals_tag_ids = rec._get_tags_from_param(
                "dms_enterprise.approvals_tag_ids"
            )

    def _set_approvals_tag_ids(self):
        for rec in self:
            rec._set_tags_to_param(
                "dms_enterprise.approvals_tag_ids", rec.documents_approvals_tag_ids
            )

    @api.depends_context("company")
    def _compute_sign_folder_id(self):
        for rec in self:
            rec.documents_sign_folder_id = rec._get_folder_from_param(
                "dms_enterprise.sign_folder_id"
            )

    def _set_sign_folder_id(self):
        for rec in self:
            rec._set_folder_to_param(
                "dms_enterprise.sign_folder_id", rec.documents_sign_folder_id.id
            )
            rec._sync_rule("sign", rec.documents_sign_folder_id)

    # ── Rule Sync ─────────────────────────────────────────────────────────────
    def _sync_rule(self, area, folder):
        """Keep the dms.folder.rule for this area in sync with the configured folder."""
        if area not in _AREA_MODELS:
            return
        model_name, label = _AREA_MODELS[area]

        # Resolve ir.model
        ir_model = self.env["ir.model"].sudo().search(
            [("model", "=", model_name)], limit=1
        )
        if not ir_model:
            return

        # Find existing rule
        rule = self.env["dms.folder.rule"].sudo().search(
            [("area", "=", area), ("model_id", "=", ir_model.id)], limit=1
        )
        if folder:
            vals = {
                "name": f"Auto-route {label}",
                "model_id": ir_model.id,
                "directory_id": folder.id,
                "area": area,
                "active": True,
            }
            if rule:
                rule.write({"directory_id": folder.id, "active": True})
            else:
                self.env["dms.folder.rule"].sudo().create(vals)
        else:
            # Folder cleared → deactivate rule
            if rule:
                rule.write({"active": False})
