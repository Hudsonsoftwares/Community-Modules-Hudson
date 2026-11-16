"""Classify the allergy status of existing patients from what is already written in Allergies.

Nothing is guessed: an empty field stays 'Not Recorded'. Verification stamps are left empty because
nobody confirmed the information as part of this upgrade.
"""
from odoo.addons.dental_patient.models.res_partner import clean_allergy_text
from odoo.tools import html2plaintext


def migrate(cr, version):
    cr.execute("SELECT id, allergies FROM res_partner WHERE allergies IS NOT NULL")
    known, none = [], []
    for partner_id, allergies in cr.fetchall():
        if clean_allergy_text(allergies):
            known.append(partner_id)
        elif html2plaintext(allergies or '').strip():
            none.append(partner_id)
    for status, ids in (('known', known), ('none', none)):
        if ids:
            cr.execute("UPDATE res_partner SET allergy_status = %s WHERE id = ANY(%s)", (status, ids))
    cr.execute("UPDATE res_partner SET allergy_status = 'unknown' WHERE allergy_status IS NULL")
