# -*- coding: utf-8 -*-
import base64
import json
from psycopg2 import IntegrityError
from odoo import http, _
from odoo.http import request
from odoo.exceptions import ValidationError
from odoo.addons.website.controllers.form import WebsiteForm


class HelpdeskManagementWebsiteForm(WebsiteForm):

    def _handle_website_form(self, model_name, **kwargs):
        """
        Intercept website form submissions for helpdesk.management.ticket.
        """
        if model_name == 'helpdesk.management.ticket':
            # 1. Determine Stage (get the one with lowest sequence, default to 'New' or fallback)
            lowest_stage_id = None
            stages = request.env['helpdesk.management.stage'].sudo().search([])
            if stages:
                # Find the stage with the minimum sequence
                sequence = stages.mapped('sequence')
                lowest_sequence = stages.filtered(lambda x: x.sequence == min(sequence))
                if lowest_sequence:
                    lowest_stage_id = lowest_sequence[0]
                    
            if not lowest_stage_id:
                # Fallback if no stage exists (shouldn't happen with demo data)
                return json.dumps({'error': "No stage found for tickets."})

            # 2. Determine Customer (Partner)
            partner_create = request.env['res.partner']
            if request.env.user and request.env.user.id != request.env.ref('base.public_user').id:
                partner_create = request.env.user.partner_id
            else:
                email = kwargs.get('email_from') or kwargs.get('partner_email')
                if email:
                    existing_partner = request.env['res.partner'].sudo().search([('email', '=', email)], limit=1)
                    if existing_partner:
                        partner_create = existing_partner
                    else:
                        name = kwargs.get('customer_name') or kwargs.get('partner_name') or email
                        phone = kwargs.get('phone') or kwargs.get('partner_phone')
                        partner_create = request.env['res.partner'].sudo().create({
                            'name': name,
                            'email': email,
                            'phone': phone,
                        })

            # 3. Map values to helpdesk.management.ticket
            rec_val = {
                'subject': kwargs.get('subject') or 'Website Ticket',
                'description': kwargs.get('description'),
                'partner_name': partner_create.name if partner_create else (kwargs.get('customer_name') or kwargs.get('partner_name')),
                'partner_email': partner_create.email if partner_create else (kwargs.get('email_from') or kwargs.get('partner_email')),
                'partner_phone': partner_create.phone if partner_create else (kwargs.get('phone') or kwargs.get('partner_phone')),
                'priority': kwargs.get('priority', '0'),
                'stage_id': lowest_stage_id.id,
            }
            if partner_create:
                rec_val['partner_id'] = partner_create.id

            # Extra mapping for fields that might be in standard templates
            if kwargs.get('ticket_type_id'):
                rec_val['ticket_type_id'] = int(kwargs.get('ticket_type_id'))
            if kwargs.get('category_id') or kwargs.get('category'):
                rec_val['category_id'] = int(kwargs.get('category_id') or kwargs.get('category'))

            # 4. Create the Ticket
            ticket_id = request.env['helpdesk.management.ticket'].sudo().create(rec_val)

            # 5. Process Attachments
            attachments = []
            attachment_index = 0
            while f"ticket_attachment[0][{attachment_index}]" in kwargs:
                attachment_key = f"ticket_attachment[0][{attachment_index}]"
                attachments.append(kwargs[attachment_key])
                attachment_index += 1
                
            # Generic attachment handler for standard Odoo file uploads
            for key, val in kwargs.items():
                if hasattr(val, 'filename') and val not in attachments:
                    attachments.append(val)

            for attachment in attachments:
                if hasattr(attachment, 'read'):
                    attached_file = attachment.read()
                    request.env['ir.attachment'].sudo().create({
                        'name': attachment.filename,
                        'res_model': 'helpdesk.management.ticket',
                        'res_id': ticket_id.id,
                        'type': 'binary',
                        'datas': base64.encodebytes(attached_file),
                    })

            # 6. Session setup for success page redirection
            model_record = request.env['ir.model'].sudo().search([('model', '=', model_name)], limit=1)
            if model_record:
                request.session['form_builder_model_model'] = model_record.model
                request.session['form_builder_model'] = model_record.name
                request.session['form_builder_id'] = ticket_id.id
                
            request.session['ticket_number'] = ticket_id.name
            request.session['ticket_id'] = ticket_id.id
            
            return json.dumps({'id': ticket_id.id})
            
        else:
            # Pass to standard controller for all other models
            return super(HelpdeskManagementWebsiteForm, self)._handle_website_form(model_name, **kwargs)
