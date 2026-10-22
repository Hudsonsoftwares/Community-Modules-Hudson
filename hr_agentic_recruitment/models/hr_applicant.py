import json
import requests
import base64
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

try:
    import PyPDF2
    import io
except ImportError:
    PyPDF2 = None

class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    ai_match_score = fields.Integer(string="AI Match Score", readonly=True, help="Score from 0 to 100 given by AI.")
    ai_summary = fields.Text(string="AI Summary", readonly=True)
    ai_analysis_status = fields.Selection([
        ('pending', 'Pending'),
        ('done', 'Analyzed'),
        ('failed', 'Failed')
    ], string="AI Status", default='pending', readonly=True)

    def action_analyze_resume_ai(self):
        """Action triggered by the 'AI Analyze Resume' button"""
        for applicant in self:
            applicant._analyze_single_resume()
            
    def _extract_text_from_attachment(self, attachment):
        if not attachment or not attachment.datas:
            return ""
        
        text = ""
        if attachment.mimetype == 'application/pdf' and PyPDF2:
            try:
                pdf_data = base64.b64decode(attachment.datas)
                reader = PyPDF2.PdfReader(io.BytesIO(pdf_data))
                for page in reader.pages:
                    text += page.extract_text() + "\n"
                return text
            except Exception as e:
                _logger.warning(f"Failed to extract PDF text: {e}")
        
        return "Resume processing not fully supported without PyPDF2 or for non-PDF files."

    def _analyze_single_resume(self):
        self.ensure_one()
        
        provider = self.env['ir.config_parameter'].sudo().get_param('hr_agentic_recruitment.ai_provider', 'gemini')
        api_key = self.env['ir.config_parameter'].sudo().get_param('hr_agentic_recruitment.ai_api_key')
        model_name = self.env['ir.config_parameter'].sudo().get_param('hr_agentic_recruitment.ai_model_name', 'gemini-1.5-flash')
        system_prompt = self.env['ir.config_parameter'].sudo().get_param('hr_agentic_recruitment.ai_system_prompt')
        
        if not api_key:
            raise UserError(_("Please configure the AI API Key in Recruitment Settings."))
            
        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'hr.applicant'),
            ('res_id', '=', self.id)
        ], limit=1, order='id desc')
        
        if not attachment:
            raise UserError(_("No resume attachment found for this applicant."))
            
        resume_text = self._extract_text_from_attachment(attachment)
        job_description = self.job_id.description or "No specific job description provided. Please evaluate general skills."
        
        prompt = f"Job Description:\n{job_description}\n\n---\nApplicant Resume:\n{resume_text}"

        try:
            if provider == 'gemini':
                result = self._call_gemini(api_key, model_name, system_prompt, prompt)
            else:
                result = self._call_openai(api_key, model_name, system_prompt, prompt)
                
            self.write({
                'ai_match_score': result.get('score', 0),
                'ai_summary': result.get('summary', 'No summary provided.'),
                'ai_analysis_status': 'done'
            })
            
            self.message_post(body=f"<b>AI Analysis Complete:</b><br/>Score: {self.ai_match_score}/100<br/>Summary: {self.ai_summary}")
            
        except Exception as e:
            self.write({'ai_analysis_status': 'failed'})
            self.message_post(body=f"AI Analysis Failed: {str(e)}")
            _logger.error(f"AI Analysis error: {e}")

    def _call_gemini(self, api_key, model_name, system_prompt, user_prompt):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}
        payload = {
            "system_instruction": {
                "parts": {"text": system_prompt + "\\nIMPORTANT: Return ONLY raw JSON format without markdown blocks."}
            },
            "contents": [{
                "parts": [{"text": user_prompt}]
            }],
            "generationConfig": {
                "response_mime_type": "application/json"
            }
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        text_response = data['candidates'][0]['content']['parts'][0]['text']
        try:
            return json.loads(text_response)
        except json.JSONDecodeError:
            if text_response.startswith('```json'):
                text_response = text_response.split('```json')[1].split('```')[0]
            return json.loads(text_response.strip())

    def _call_openai(self, api_key, model_name, system_prompt, user_prompt):
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            'Authorization': f"Bearer {api_key}",
            'Content-Type': 'application/json'
        }
        payload = {
            "model": model_name,
            "response_format": { "type": "json_object" },
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return json.loads(data['choices'][0]['message']['content'])
