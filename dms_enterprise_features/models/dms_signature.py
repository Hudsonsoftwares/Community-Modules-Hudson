# Copyright 2024 Hudson Community
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import base64
import io
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    from PyPDF2 import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
except ImportError:
    _logger.debug("PyPDF2 or reportlab not installed.")

class DMSFileSignatureRequest(models.Model):
    _name = "dms.file.signature.request"
    _description = "Document Signature Request"
    _rec_name = "recipient_id"
    _inherit = ['portal.mixin', 'mail.thread']

    revision_id = fields.Many2one(
        comodel_name="dms.file.revision",
        string="Document Revision",
        required=True,
        ondelete="cascade"
    )
    pdf_content = fields.Binary(
        compute="_compute_pdf_content",
        string="Document Preview",
    )
    recipient_id = fields.Many2one(
        comodel_name="res.users",
        string="Recipient",
        required=True
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('sent', 'Sent'),
            ('signed', 'Signed')
        ],
        string="Status",
        default="draft",
        tracking=True
    )
    page_number = fields.Integer(string="Page Number", default=1)
    pos_x = fields.Float(string="X Position", default=100.0)
    pos_y = fields.Float(string="Y Position", default=100.0)
    signature_image = fields.Binary(
        string="Signature",
        attachment=True
    )
    signed_date = fields.Datetime(string="Signed On")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Grant DMS user group to recipients so they can see the app
        dms_user_group = self.env.ref('dms.group_dms_user', raise_if_not_found=False)
        if dms_user_group:
            for record in records:
                if record.recipient_id and not record.recipient_id.share:
                    dms_user_group.sudo().write({'user_ids': [(4, record.recipient_id.id)]})
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'recipient_id' in vals:
            dms_user_group = self.env.ref('dms.group_dms_user', raise_if_not_found=False)
            if dms_user_group:
                for record in self:
                    if record.recipient_id and not record.recipient_id.share:
                        dms_user_group.sudo().write({'user_ids': [(4, record.recipient_id.id)]})
        return res
        
    @api.depends('revision_id.content', 'pos_x', 'pos_y', 'page_number', 'state')
    def _compute_pdf_content(self):
        for req in self:
            if req.state == 'signed' or not req.revision_id.content:
                req.pdf_content = req.revision_id.content
            else:
                try:
                    req.pdf_content = req._generate_preview_pdf()
                except Exception as e:
                    _logger.error(f"Failed to generate preview PDF: {e}")
                    req.pdf_content = req.revision_id.content

    def _generate_preview_pdf(self):
        self.ensure_one()
        if self.revision_id.file_id.mimetype != 'application/pdf':
            return self.revision_id.content

        original_pdf = base64.b64decode(self.revision_id.content)
        
        watermark_io = io.BytesIO()
        c = canvas.Canvas(watermark_io)
        
        # Transparent red box
        c.setFillColorRGB(1, 0, 0, 0.2)
        c.rect(self.pos_x, self.pos_y, 150, 50, fill=1, stroke=0)
        c.setFillColorRGB(1, 0, 0, 1)
        c.rect(self.pos_x, self.pos_y, 150, 50, fill=0, stroke=1)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(self.pos_x + 35, self.pos_y + 20, "SIGN HERE")
        c.save()
        
        watermark_io.seek(0)
        watermark_pdf = PdfReader(watermark_io)
        watermark_page = watermark_pdf.pages[0]

        pdf_reader = PdfReader(io.BytesIO(original_pdf))
        pdf_writer = PdfWriter()

        page_idx = self.page_number - 1
        if page_idx < 0 or page_idx >= len(pdf_reader.pages):
            page_idx = 0
            
        for i, page in enumerate(pdf_reader.pages):
            if i == page_idx:
                page.merge_page(watermark_page)
            pdf_writer.add_page(page)

        output_io = io.BytesIO()
        pdf_writer.write(output_io)
        return base64.b64encode(output_io.getvalue())
    
    def _compute_access_url(self):
        super()._compute_access_url()
        for request in self:
            request.access_url = f'/my/dms/signature/{request.id}'

    def action_send(self):
        self.write({'state': 'sent'})
        # In a real scenario, this would send an email with the access URL
        return True

    def action_apply_signature(self):
        self.ensure_one()
        if not self.signature_image:
            raise UserError("Please sign the document before applying.")
        self.process_signature(self.signature_image)
        
        # Check if all signatures for this file are done, if so, approve it
        pending_sigs = self.env['dms.file.signature.request'].search([
            ('revision_id', '=', self.revision_id.id),
            ('state', '!=', 'signed')
        ])
        if not pending_sigs:
            self.revision_id.file_id.status = 'approved'
        return True

    def process_signature(self, signature_base64):
        self.ensure_one()
        self.write({
            'signature_image': signature_base64,
            'signed_date': fields.Datetime.now(),
            'state': 'signed'
        })
        self._stamp_pdf()

    def _stamp_pdf(self):
        """Stamps the signature image onto the PDF and creates a new revision."""
        if not self.revision_id.content or not self.signature_image:
            return
        
        # Check if the document is a PDF
        if self.revision_id.file_id.mimetype != 'application/pdf':
            raise UserError("Only PDF documents can be stamped with signatures.")

        try:
            original_pdf = base64.b64decode(self.revision_id.content)
            signature_img = base64.b64decode(self.signature_image)
            
            # Create a watermark PDF with ReportLab
            watermark_io = io.BytesIO()
            c = canvas.Canvas(watermark_io)
            img = ImageReader(io.BytesIO(signature_img))
            
            # Draw image at pos_x, pos_y. Size is arbitrary (e.g. 150x50)
            c.drawImage(img, self.pos_x, self.pos_y, width=150, height=50, mask='auto')
            c.save()
            
            watermark_io.seek(0)
            watermark_pdf = PdfReader(watermark_io)
            watermark_page = watermark_pdf.pages[0]

            # Read original PDF
            pdf_reader = PdfReader(io.BytesIO(original_pdf))
            pdf_writer = PdfWriter()

            page_idx = self.page_number - 1
            if page_idx < 0 or page_idx >= len(pdf_reader.pages):
                page_idx = 0 # Fallback to first page
                
            for i, page in enumerate(pdf_reader.pages):
                if i == page_idx:
                    page.merge_page(watermark_page)
                pdf_writer.add_page(page)

            output_io = io.BytesIO()
            pdf_writer.write(output_io)
            signed_pdf_base64 = base64.b64encode(output_io.getvalue())
            
            # Create new signed revision
            new_version_num = str(int(self.revision_id.version) + 1) if self.revision_id.version.isdigit() else self.revision_id.version + "_signed"
            new_revision = self.env['dms.file.revision'].create({
                'file_id': self.revision_id.file_id.id,
                'version': new_version_num,
                'content': signed_pdf_base64,
                'file_name': f"signed_{self.revision_id.file_name or self.revision_id.file_id.name}",
                'comments': f"Signed by {self.recipient_id.name}"
            })
            
            # Action make current already called by create if it's the first, but here we explicitly make it current
            new_revision.action_make_current()
            
            # Update ALL pending signature requests to point to the new revision!
            pending_requests = self.env['dms.file.signature.request'].search([
                ('revision_id', '=', self.revision_id.id),
                ('id', '!=', self.id)
            ])
            pending_requests.write({'revision_id': new_revision.id})
            
            # Update OUR own revision_id so the preview updates!
            self.revision_id = new_revision.id


        except Exception as e:
            _logger.error(f"Failed to stamp PDF: {str(e)}")
            raise UserError(f"Failed to apply signature to PDF. Ensure PyPDF2 and reportlab are installed. Error: {str(e)}")
