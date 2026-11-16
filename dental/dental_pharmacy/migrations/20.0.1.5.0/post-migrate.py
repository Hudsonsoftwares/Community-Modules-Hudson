# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """The patient email moved to mail_template_prescription_patient (new professional layout).
    The old template was noupdate, so it would otherwise stay behind as a duplicate."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    old = env.ref('dental_pharmacy.mail_template_prescription_to_patient', raise_if_not_found=False)
    if old:
        old.unlink()
