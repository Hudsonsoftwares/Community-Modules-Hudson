# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class IrAttachment(models.Model):
    """Extend ir.attachment to route new attachments to DMS via folder rules."""

    _inherit = "ir.attachment"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Skip if we're already inside DMS file creation to avoid infinite loops
        if not self.env.context.get("dms_file") and not self.env.context.get(
            "dms_enterprise_routing"
        ):
            records.with_context(dms_enterprise_routing=True)._route_to_dms_folders()
        return records

    def write(self, vals):
        res = super().write(vals)
        # Re-route when attaching to a record (e.g., website forms, chatter)
        if (
            not self.env.context.get("dms_file")
            and not self.env.context.get("dms_enterprise_routing")
            and ("res_model" in vals or "res_id" in vals)
        ):
            self.with_context(dms_enterprise_routing=True)._route_to_dms_folders()
        return res

    def _route_to_dms_folders(self):
        """For each attachment, find a matching dms.folder.rule and route it."""
        FolderRule = self.env["dms.folder.rule"].sudo()
        for attachment in self:
            if not attachment.res_model or not attachment.res_id:
                continue
            # Check if the area for this model is enabled in settings
            if not self._is_area_enabled(attachment.res_model):
                continue
            rule = FolderRule.find_matching_rule(attachment.res_model)
            if rule:
                try:
                    rule.route_attachment(attachment)
                except Exception as e:
                    _logger.warning(
                        "DMS Enterprise: failed to route attachment %s: %s",
                        attachment.id,
                        e,
                    )

    def _is_area_enabled(self, model_name):
        """Check if the DMS auto-routing is enabled for the given model's area."""
        ICP = self.env["ir.config_parameter"].sudo()
        _model_to_param = {
            "hr.employee": "dms_enterprise.hr_enabled",
            "hr.contract": "dms_enterprise.hr_enabled",
            "hr.payslip": "dms_enterprise.hr_enabled",
            "hr.applicant": "dms_enterprise.recruitment_enabled",
            "hr.job": "dms_enterprise.recruitment_enabled",
            "account.move": "dms_enterprise.accounting_enabled",
            "account.journal": "dms_enterprise.accounting_enabled",
            "product.template": "dms_enterprise.product_enabled",
            "product.product": "dms_enterprise.product_enabled",
            "project.project": "dms_enterprise.project_enabled",
            "project.task": "dms_enterprise.project_enabled",
            "approval.request": "dms_enterprise.approvals_enabled",
            "sign.request": "dms_enterprise.sign_enabled",
        }
        param_key = _model_to_param.get(model_name)
        if not param_key:
            # Unknown model — check if any active rule exists
            return bool(
                self.env["dms.folder.rule"].sudo().search(
                    [("model_name", "=", model_name), ("active", "=", True)],
                    limit=1,
                )
            )
        return ICP.get_param(param_key, "False") in ("True", "1", "true")
