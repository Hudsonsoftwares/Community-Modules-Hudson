# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from . import models
from . import controllers


def post_init_hook(env):
    """Create default dms.folder.rule records for each business area.

    We do this in Python rather than XML so we can safely skip models that
    are not installed in the current Odoo instance (e.g., if sign, approvals,
    or project are not installed, we just skip those rules).
    """
    _create_default_rules(env)


def _create_default_rules(env):
    """Create one auto-assignment rule per business area if the target model exists."""

    IcpParam = env["ir.config_parameter"].sudo()
    FolderRule = env["dms.folder.rule"].sudo()
    IrModel = env["ir.model"].sudo()

    # Map: area_key → (model_name, display_label, create_subfolder, config_folder_param)
    area_config = [
        ("hr",          "hr.employee",       "Human Resources",  True,  "dms_enterprise.hr_folder_id"),
        ("hr",          "hr.contract",       "HR Contracts",     True,  "dms_enterprise.hr_folder_id"),
        ("recruitment", "hr.applicant",      "Recruitment",      True,  "dms_enterprise.recruitment_folder_id"),
        ("accounting",  "account.move",      "Accounting",       False, "dms_enterprise.accounting_folder_id"),
        ("product",     "product.template",  "Products",         True,  "dms_enterprise.product_folder_id"),
        ("project",     "project.project",   "Projects",         True,  "dms_enterprise.project_folder_id"),
        ("approvals",   "approval.request",  "Approvals",        False, "dms_enterprise.approvals_folder_id"),
        ("sign",        "sign.request",      "Sign",             False, "dms_enterprise.sign_folder_id"),
    ]

    for area, model_name, label, create_sub, folder_param in area_config:
        # Skip if model is not installed
        ir_model = IrModel.search([("model", "=", model_name)], limit=1)
        if not ir_model:
            continue

        # Get folder from config param
        folder_id_str = IcpParam.get_param(folder_param, "")
        if not folder_id_str:
            continue

        try:
            folder_id = int(folder_id_str)
        except (ValueError, TypeError):
            continue

        folder = env["dms.directory"].sudo().browse(folder_id)
        if not folder.exists():
            continue

        # Skip if rule already exists
        existing = FolderRule.search([
            ("model_id", "=", ir_model.id),
            ("area", "=", area),
        ], limit=1)
        if existing:
            continue

        FolderRule.create({
            "name": f"Auto-route {label}",
            "area": area,
            "model_id": ir_model.id,
            "directory_id": folder_id,
            "create_subfolder": create_sub,
            "active": True,  # Activated by default to mimic Enterprise Edition
            "sequence": {
                "hr": 10,
                "recruitment": 20,
                "accounting": 30,
                "product": 40,
                "project": 50,
                "approvals": 60,
                "sign": 70,
            }.get(area, 99),
        })
