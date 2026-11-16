# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Payslips now have their own folder: Payroll / <tax year> / Payslips (next to Tax Proofs)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    moved = env['hr.payslip']._hds_dms_move_to_payslip_folders()
    _logger.info("Payroll Documents: %s payslip file(s) moved to the Payslips folders.", moved)
