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
            # Avoid routing files belonging directly to dms.file or dms.directory
            if attachment.res_model in ("dms.file", "dms.directory"):
                continue

            record = None
            if attachment.res_model in self.env:
                try:
                    record = self.env[attachment.res_model].sudo().browse(attachment.res_id)
                    if not record.exists():
                        record = None
                except Exception:
                    record = None

            rule = FolderRule.find_matching_rule(attachment.res_model, record=record)
            if rule:
                try:
                    rule.route_attachment(attachment)
                except Exception as e:
                    _logger.warning(
                        "DMS Enterprise: failed to route attachment %s (rule '%s'): %s",
                        attachment.id,
                        rule.name,
                        e,
                    )
