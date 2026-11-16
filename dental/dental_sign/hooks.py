# -*- coding: utf-8 -*-
import io
import logging
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from odoo import Command

_logger = logging.getLogger(__name__)

CONSENT_DETAILS = {
    'Dental Implant': {
        'title': 'INFORMED CONSENT FOR DENTAL IMPLANT SURGERY',
        'desc': 'Placement of biocompatible titanium/zirconia dental implant fixture into the jawbone to support dental prosthetics.',
        'risks': 'Pain, swelling, bruising, infection, temporary or permanent numbness/altered sensation to lower lip/chin/tongue, sinus complications, implant rejection or osseointegration failure requiring removal.',
        'alternatives': 'Fixed bridge, removable partial or full denture, or no treatment leaving the space vacant.',
    },
    'Root Canal Treatment': {
        'title': 'INFORMED CONSENT FOR ENDODONTIC (ROOT CANAL) TREATMENT',
        'desc': 'Removal of infected or damaged dental pulp tissue, disinfection of the root canal system, and hermetic obturation with biocompatible filling material.',
        'risks': 'Post-operative discomfort or tenderness, temporary pain, instrumentation breakage in calcified canals, perforation of root or crown, re-infection requiring re-treatment or apical surgery, tooth fracture.',
        'alternatives': 'Extraction of the tooth followed by prosthetic replacement (implant, bridge, denture), or no treatment.',
    },
    'Tooth Extraction': {
        'title': 'INFORMED CONSENT FOR TOOTH EXTRACTION',
        'desc': 'Surgical or non-surgical removal of damaged, non-restorable, impacted, or diseased teeth.',
        'risks': 'Bleeding, swelling, pain, dry socket (alveolar osteitis), infection, nerve injury causing numbness of lip/tongue/chin, root tip displacement, sinus perforation in upper molars.',
        'alternatives': 'Root canal therapy, periodontal therapy, crown restoration, or no treatment.',
    },
    'Crown': {
        'title': 'INFORMED CONSENT FOR CROWN RESTORATION',
        'desc': 'Preparation and fitting of a full coverage dental crown (ceramic, zirconia, or metal) to restore structural integrity, function, and aesthetics of a compromised tooth.',
        'risks': 'Tooth sensitivity to hot/cold, pulpitis potentially necessitating subsequent root canal treatment, shade variation under different lightings, crown debonding or fracture.',
        'alternatives': 'Large direct filling, inlay/onlay, or tooth extraction.',
    },
    'Bridge': {
        'title': 'INFORMED CONSENT FOR FIXED DENTAL BRIDGE',
        'desc': 'Preparation of adjacent abutment teeth to anchor a permanent prosthetic bridge replacing one or more missing teeth.',
        'risks': 'Pulp sensitivity or nerve inflammation in abutment teeth, difficulty in flossing/hygiene maintenance, periodontal inflammation, bridge dislodgement, bone loss beneath pontic.',
        'alternatives': 'Dental implant restoration, removable partial denture, or leaving the edentulous space.',
    },
    'Dental Filling': {
        'title': 'INFORMED CONSENT FOR DENTAL RESTORATION (FILLING)',
        'desc': 'Excavation of decayed tooth material and placement of composite resin or glass ionomer filling material.',
        'risks': 'Post-operative sensitivity, nerve irritation, restoration wear, recurrent decay along margins, need for crown if tooth structure proves insufficient.',
        'alternatives': 'Inlay/onlay, extraction, or watchful monitoring (not recommended for active caries).',
    },
    'Braces': {
        'title': 'INFORMED CONSENT FOR ORTHODONTIC TREATMENT',
        'desc': 'Realignment and correction of dental malocclusion and arch discrepancies using brackets, wires, and auxiliary appliances.',
        'risks': 'Transient tooth soreness, mucosal irritation, root resorption, decalcification/white spots if oral hygiene is inadequate, relapse if retainers are not worn.',
        'alternatives': 'Clear aligners, surgical orthodontics, cosmetic veneers, or accepting existing occlusion.',
    },
}

def generate_consent_pdf(title, treatment_name, desc, risks, alternatives):
    """Generate a clean, high-resolution A4/Letter medical consent PDF buffer."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )
    styles = getSampleStyleSheet()

    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=18,
        alignment=1, # Center
        textColor=colors.HexColor('#1f2937'),
        spaceAfter=15,
    )
    section_title = ParagraphStyle(
        'SectionTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#0f766e'),
        spaceBefore=8,
        spaceAfter=3,
    )
    body_style = ParagraphStyle(
        'BodyStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor('#374151'),
    )
    declaration_style = ParagraphStyle(
        'DeclarationStyle',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#4b5563'),
        spaceBefore=10,
        spaceAfter=15,
    )

    story = [
        Paragraph("DENTAL CLINIC &amp; HOSPITAL NETWORK", ParagraphStyle('ClinicHeader', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, alignment=1, textColor=colors.HexColor('#6b7280'), spaceAfter=4)),
        Paragraph(title, header_style),
        Spacer(1, 4),
        Paragraph("<b>1. PROCEDURE OVERVIEW &amp; CLINICAL PURPOSE</b>", section_title),
        Paragraph(desc, body_style),
        Spacer(1, 6),
        Paragraph("<b>2. POTENTIAL RISKS, COMPLICATIONS &amp; DISCOMFORTS</b>", section_title),
        Paragraph(risks, body_style),
        Spacer(1, 6),
        Paragraph("<b>3. REASONABLE TREATMENT ALTERNATIVES</b>", section_title),
        Paragraph(alternatives, body_style),
        Spacer(1, 6),
        Paragraph("<b>4. PATIENT ACKNOWLEDGEMENT &amp; INFORMED CONSENT</b>", section_title),
        Paragraph(
            "I confirm that the nature, purpose, anticipated benefits, foreseeable risks, and alternatives of the proposed treatment have been thoroughly explained to me by the treating dental team. I have been given adequate opportunity to ask questions and have all inquiries answered to my full satisfaction. I hereby consent freely to the execution of this procedure.",
            declaration_style
        ),
        Spacer(1, 10),
    ]

    # Signature blocks table
    sig_data = [
        [
            Paragraph("<b>Patient / Legal Guardian Signature:</b><br/><br/><br/><br/>________________________________________<br/>Print Name:<br/>Date:", body_style),
            Paragraph("<b>Treating Dentist / Doctor Signature:</b><br/><br/><br/><br/>________________________________________<br/>Doctor Name:<br/>License / Registration:", body_style)
        ]
    ]
    t = Table(sig_data, colWidths=[260, 260])
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t)

    doc.build(story)
    return buf.getvalue()


def post_init_hook(env):
    """Create default Hudson Sign consent templates for all dental treatments requiring consent."""
    _logger.info("Initializing Dental Sign Consent Templates...")
    HudsonSignTemplate = env['hudson.sign.template']
    HudsonSignRole = env['hudson.sign.template.role']
    HudsonSignItem = env['hudson.sign.template.item']
    HudsonSignItemType = env['hudson.sign.item.type']
    ProductTemplate = env['product.template']
    IrAttachment = env['ir.attachment']

    sig_type = HudsonSignItemType.search([('item_type', '=', 'signature')], limit=1)
    date_type = HudsonSignItemType.search([('item_type', '=', 'date')], limit=1)

    treatments = ProductTemplate.search([('is_dental_treatment', '=', True)])
    for treatment in treatments:
        treatment_name = treatment.name
        details = CONSENT_DETAILS.get(treatment_name)
        if not details:
            details = {
                'title': f'INFORMED CONSENT FOR {treatment_name.upper()}',
                'desc': f'Performance of clinical procedure {treatment_name} in accordance with dental care standards.',
                'risks': 'Post-operative discomfort, sensitivity, swelling, unexpected biological responses, or necessity for secondary intervention.',
                'alternatives': 'Alternative prosthetic, therapeutic, or surgical options as discussed during clinical consultation.',
            }

        existing_template = HudsonSignTemplate.search([('treatment_id', '=', treatment.id)], limit=1)
        if existing_template:
            treatment.consent_template_id = existing_template.id
            continue

        pdf_content = generate_consent_pdf(
            details['title'],
            treatment_name,
            details['desc'],
            details['risks'],
            details['alternatives']
        )

        template_name = f"Informed Consent - {treatment_name}"
        file_name = f"{template_name}.pdf"
        attachment = IrAttachment.create({
            'name': file_name,
            'type': 'binary',
            'mimetype': 'application/pdf',
            'raw': pdf_content,
        })

        template = HudsonSignTemplate.create({
            'name': template_name,
            'attachment_id': attachment.id,
            'treatment_id': treatment.id,
            'active': True,
            'favorited_ids': [Command.link(env.user.id)],
        })

        # Roles: Patient and Doctor
        patient_role = HudsonSignRole.create({
            'name': 'Patient / Guardian',
            'sequence': 1,
            'color': '#d1fae5',
            'border_color': '#10b981',
            'text_color': '#065f46',
            'template_id': template.id,
        })
        doctor_role = HudsonSignRole.create({
            'name': 'Dentist',
            'sequence': 2,
            'color': '#e0e7ff',
            'border_color': '#6366f1',
            'text_color': '#3730a3',
            'template_id': template.id,
        })

        # Place Signature and Date fields at the bottom of the page
        if sig_type:
            # Patient signature box (bottom left)
            HudsonSignItem.create({
                'template_id': template.id,
                'role_id': patient_role.id,
                'type_id': sig_type.id,
                'page_number': 1,
                'pos_x': 0.08,
                'pos_y': 0.72,
                'width': 0.35,
                'height': 0.08,
                'mandatory': True,
            })
            # Doctor signature box (bottom right)
            HudsonSignItem.create({
                'template_id': template.id,
                'role_id': doctor_role.id,
                'type_id': sig_type.id,
                'page_number': 1,
                'pos_x': 0.55,
                'pos_y': 0.72,
                'width': 0.35,
                'height': 0.08,
                'mandatory': True,
            })
        if date_type:
            # Patient date box
            HudsonSignItem.create({
                'template_id': template.id,
                'role_id': patient_role.id,
                'type_id': date_type.id,
                'page_number': 1,
                'pos_x': 0.08,
                'pos_y': 0.82,
                'width': 0.22,
                'height': 0.04,
                'mandatory': True,
            })

        # Link template to treatment
        treatment.consent_template_id = template.id
        if treatment_name in CONSENT_DETAILS:
            treatment.is_consent_required = True

    _logger.info("Dental Sign Consent Templates initialized successfully.")
