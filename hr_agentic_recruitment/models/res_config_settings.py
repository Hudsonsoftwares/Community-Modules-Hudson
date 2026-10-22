from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ai_provider = fields.Selection([
        ('openai', 'OpenAI'),
        ('gemini', 'Google Gemini'),
    ], string="AI Provider", default='gemini', config_parameter='hr_agentic_recruitment.ai_provider')
    
    ai_api_key = fields.Char(string="AI API Key", config_parameter='hr_agentic_recruitment.ai_api_key')
    ai_model_name = fields.Char(string="AI Model Name", default="gemini-1.5-flash", config_parameter='hr_agentic_recruitment.ai_model_name')
    ai_system_prompt = fields.Char(string="AI System Prompt", config_parameter='hr_agentic_recruitment.ai_system_prompt', 
        default="You are an expert HR agent. Review the provided candidate resume text against the job description. Return ONLY a JSON object with two keys: 'score' (an integer from 0 to 100) and 'summary' (a brief 2-sentence explanation of the fit).")
