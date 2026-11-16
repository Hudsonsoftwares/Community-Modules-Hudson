import json

from odoo import api, fields, models


class AbdmFhirPreview(models.TransientModel):
    """Read-only window showing the FHIR records a record would share."""
    _name = 'abdm.fhir.preview'
    _description = 'ABDM Record Preview'

    name = fields.Char(readonly=True)
    summary = fields.Text(readonly=True)
    content = fields.Text(string='FHIR (JSON)', readonly=True)

    @api.model
    def open(self, title, records):
        """``records``: list of dicts with hi_type, reference, date, bundle."""
        lines = ['%s  ·  %s  ·  %s' % (r['hi_type'], r['reference'], r.get('date') or '') for r in records]
        preview = self.create({
            'name': title,
            'summary': '\n'.join(lines) or self.env._('Nothing to share yet: complete an examination or issue a prescription first.'),
            'content': json.dumps([r['bundle'] for r in records], indent=2, ensure_ascii=False, default=str),
        })
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('ABDM Records: %s', title),
            'res_model': self._name,
            'res_id': preview.id,
            'view_mode': 'form',
            'target': 'new',
        }
