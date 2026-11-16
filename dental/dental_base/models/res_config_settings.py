from odoo import api, models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    @api.model_create_multi
    def create(self, vals_list):
        # Workaround for an Odoo 20 core bug: the web client may send a binary
        # value as {'filename': ..., 'content': False}. Binary.convert_to_cache
        # then calls `.filename` on None and crashes. Normalize such values to
        # False (empty binary) before the core create processes them.
        for vals in vals_list:
            for fname, value in list(vals.items()):
                field = self._fields.get(fname)
                if (
                    field is not None
                    and field.type == 'binary'
                    and isinstance(value, dict)
                    and 'content' in value
                    and not value['content']
                ):
                    vals[fname] = False
        return super().create(vals_list)

    dental_tooth_numbering_system = fields.Selection([
        ('fdi', 'FDI Two-Digit (ISO 3950) - Recommended'),
        ('universal', 'Universal Numbering System (1-32 / A-T)'),
        ('palmer', 'Palmer Notation System'),
    ], string='Tooth Numbering System',
       default='fdi',
       config_parameter='dental_base.tooth_numbering_system',
       help='Standard notation method used for dental chart and odontogram',
    )
    dental_appointment_duration = fields.Integer(
        string='Default Slot Duration (Minutes)',
        default=30,
        config_parameter='dental_base.default_appointment_duration',
        help='Default duration in minutes for newly booked dental appointments',
    )
    dental_enable_multi_branch = fields.Boolean(
        string='Enable Multi-Branch Mode',
        default=True,
        config_parameter='dental_base.enable_multi_branch',
        help='Activate multi-branch operations and branch-level isolation',
    )
    dental_require_consent = fields.Boolean(
        string='Require Signed Consent for Procedures',
        default=True,
        config_parameter='dental_base.require_consent',
        help='Enforce signed patient consent before completing surgical or invasive dental procedures',
    )
    dental_patient_id_prefix = fields.Char(
        string='Patient ID Prefix',
        default='PT',
        config_parameter='dental_base.patient_id_prefix',
        help='Prefix for automated unique Patient ID numbering (e.g. PT-00001)',
    )
    dental_emergency_priority_enabled = fields.Boolean(
        string='Enable Emergency Queue Priority',
        default=True,
        config_parameter='dental_base.emergency_priority_enabled',
        help='Allows emergency cases to jump to the top of waiting queue tokens',
    )
