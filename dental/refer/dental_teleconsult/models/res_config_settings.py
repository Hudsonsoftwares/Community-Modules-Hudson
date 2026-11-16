# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    dental_teleconsult_enabled = fields.Boolean(
        related='company_id.dental_teleconsult_enabled', readonly=False)
    dental_teleconsult_require_prepayment = fields.Boolean(
        related='company_id.dental_teleconsult_require_prepayment', readonly=False)
    dental_teleconsult_join_before = fields.Integer(
        related='company_id.dental_teleconsult_join_before', readonly=False)
    dental_teleconsult_join_after = fields.Integer(
        related='company_id.dental_teleconsult_join_after', readonly=False)
    dental_teleconsult_reminder_minutes = fields.Integer(
        related='company_id.dental_teleconsult_reminder_minutes', readonly=False)
    dental_teleconsult_verify_identity = fields.Boolean(
        related='company_id.dental_teleconsult_verify_identity', readonly=False)
    dental_teleconsult_allow_recording = fields.Boolean(
        related='company_id.dental_teleconsult_allow_recording', readonly=False)
