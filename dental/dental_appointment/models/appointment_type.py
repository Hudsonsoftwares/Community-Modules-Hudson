# -*- coding: utf-8 -*-
from odoo import models, fields, api

class DentalAppointmentIcon(models.Model):
    """Dental Appointment Icon Library

    Provides a centralized library of medical and dental icons that users can browse,
    search, and extend by defining new icons or uploading custom graphics.
    """
    _name = 'dental.appointment.icon'
    _description = 'Dental Appointment Icon'
    _order = 'sequence, name'

    name = fields.Char(string='Icon Name', required=True, translate=True)
    icon_class = fields.Char(
        string='Font Awesome / Icon Class',
        help='Font Awesome class identifier (e.g. fa-stethoscope, fa-ambulance, fa-shield)'
    )
    category = fields.Selection([
        ('general', 'General Consultation & Visits'),
        ('diagnostic', 'Diagnostic & Examinations'),
        ('preventive', 'Cleaning & Preventive Care'),
        ('pediatric', 'Pediatric & Kids Dentistry'),
        ('endodontic', 'Endodontics & Root Canal'),
        ('restorative', 'Restorative & Fillings'),
        ('surgical', 'Oral Surgery & Extractions'),
        ('cosmetic', 'Cosmetic & Teeth Whitening'),
        ('orthodontic', 'Orthodontics & Aligners'),
        ('prosthodontic', 'Dental Implants & Prosthetics'),
        ('emergency', 'Emergency & Urgent Care'),
    ], string='Category', default='general')
    image = fields.Image(
        string='Custom Icon Image',
        max_width=512,
        max_height=512,
        help='Upload a specific image (PNG, SVG, JPG) to use instead of a font icon.'
    )
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)


class DentalAppointmentType(models.Model):
    _name = 'dental.appointment.type'
    _description = 'Dental Appointment Type'

    name = fields.Char(string='Name', required=True)
    color = fields.Integer(string='Color')
    duration = fields.Float(string='Duration (Minutes)', default=30.0)
    description = fields.Text(string='Description')
    price = fields.Float(string='Estimated Price', default=0.0)
    icon = fields.Char(
        string='Icon',
        default='fa-stethoscope',
        help='Visual icon identifier stored as Font Awesome class (e.g. fa-stethoscope, fa-ambulance).'
    )
    icon_type = fields.Selection([
        ('icon', 'Predefined Icon'),
        ('image', 'Upload Custom Image'),
    ], string='Icon Selection Mode', default='icon', required=True,
       help='Choose between selecting a standard medical/dental vector icon or uploading a custom clinic graphic.')
    image = fields.Image(
        string='Custom Icon Image',
        max_width=512,
        max_height=512,
        help='Custom image graphic for this appointment type (e.g. clinic logo, branded tooth illustration).'
    )
    appointment_icon_id = fields.Many2one(
        'dental.appointment.icon',
        string='Preset Icon',
        help='Select an icon from the Dental Appointment Icons library, or create new ones.'
    )
    required_equipment_category_ids = fields.Many2many(
        'maintenance.equipment.category',
        'dental_appt_type_equip_cat_rel',
        'type_id',
        'category_id',
        string='Required Equipment Categories',
        help='Equipment categories required for this type of appointment (e.g. Dental X-ray machine for Diagnostic Imaging).'
    )
    required_equipment_ids = fields.Many2many(
        'maintenance.equipment',
        'dental_appt_type_equip_rel',
        'type_id',
        'equipment_id',
        string='Specific Required Equipment',
        help='Specific equipment items mandatory for this appointment type.'
    )
    active = fields.Boolean(string='Active', default=True)

    @api.onchange('appointment_icon_id')
    def _onchange_appointment_icon_id(self):
        if self.appointment_icon_id:
            if self.appointment_icon_id.icon_class:
                self.icon = self.appointment_icon_id.icon_class
                self.icon_type = 'icon'
            elif self.appointment_icon_id.image:
                self.image = self.appointment_icon_id.image
                self.icon_type = 'image'
