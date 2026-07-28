# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

"""
Hudson AI Agent — Core reasoning engine.

Implements an agentic loop:
  1. User message arrives.
  2. Build context (system prompt + history + tool definitions).
  3. Call LM Studio.
  4. If the model returns a tool_call → execute tool → append result → goto 3.
  5. When the model returns a plain text response → return it to the user.

Supported tools (functions the AI can invoke):
  • get_model_schema        — describe an Odoo model's fields
  • search_read_records     — query any model with domain/fields/limit
  • create_record           — create a new record
  • update_record           — write values to existing record(s)
  • delete_record           — unlink record(s)
  • get_installed_modules   — list installed app/module names
"""

import json
import logging
import urllib.request
import urllib.error

from odoo import api, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

# ─── System prompt template ──────────────────────────────────────────────────

_DEFAULT_SYSTEM_PROMPT = """You are Hudson AI, an intelligent assistant built into Odoo. \
You have full read and write access to the Odoo database on behalf of the current user.

Your capabilities:
- Search and retrieve records from any Odoo module (sales, CRM, HR, inventory, accounting, etc.)
- Create new records (sales orders, leads, partners, tasks, etc.)
- Update existing records
- Delete records (only when explicitly asked)
- Answer questions about business data

Guidelines:
- Always use the available tools to interact with the database instead of making up data.
- CRITICAL: DO NOT output or write Python code. You are NOT a code interpreter.
- To find data, you MUST invoke the `search_read_records` tool.
- CRITICAL: NEVER guess or hallucinate database IDs! If you need an ID for a relational field (like partner_id or product_id), you MUST use the `search_read_records` tool FIRST to look up the exact integer ID from the database.
- After performing an action, confirm what you did with a friendly summary.
- If an operation fails due to access rights, explain this clearly to the user.
- Be concise and professional. Do not narrate your thought process.
- Today's date is {date}.
- The current user is: {user_name} (login: {user_login}).
"""

# ─── Tool definitions (OpenAI function-calling format) ───────────────────────

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_installed_modules",
            "description": (
                "Returns a list of installed Odoo modules/apps. "
                "Use this first to understand what is available in the system."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_model_schema",
            "description": (
                "Returns field names, types, and descriptions for a given Odoo model. "
                "Use this to understand what fields are available before querying or creating records. "
                "Common models: res.partner (contacts), sale.order (sales quotations/orders), "
                "crm.lead (CRM leads/opportunities), hr.employee (employees), "
                "project.task (tasks), account.move (invoices), stock.picking (inventory transfers), "
                "purchase.order (purchase orders), product.product (products)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "model_name": {
                        "type": "string",
                        "description": "The technical name of the Odoo model, e.g. 'sale.order' or 'res.partner'.",
                    }
                },
                "required": ["model_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_read_records",
            "description": (
                "Search and retrieve records from any Odoo model. "
                "Returns a list of records matching the domain filter. "
                "Use this to answer questions like 'who is the most productive employee', "
                "'show me open sales orders', 'find the contact John Doe', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "model_name": {
                        "type": "string",
                        "description": "Technical name of the model, e.g. 'hr.employee'.",
                    },
                    "domain": {
                        "type": "string",
                        "description": (
                            "Odoo domain filter as a string representation of a Python list. "
                            "CRITICAL RULES: \n"
                            "1. '=' is strictly case-sensitive! You MUST use the 'ilike' operator for string/name searches (e.g. \"[['name', 'ilike', 'Acoustic']]\").\n"
                            "2. There is NO 'between' operator! For date ranges, use TWO conditions: e.g. \"[['create_date', '>=', '2026-07-01'], ['create_date', '<=', '2026-07-07']]\".\n"
                            "3. Dates MUST be strings ('YYYY-MM-DD'), NEVER python datetime objects.\n"
                            "Use \"[]\" for no filter."
                        ),
                    },
                    "fields": {
                        "type": "string",
                        "description": (
                            "List of field names to return, represented as a string. "
                            "Example: \"['name', 'email', 'phone']\". "
                            "CRITICAL: You MUST explicitly specify the fields you need. If omitted, only 'id' and 'display_name' will be returned."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of records to return. Defaults to 20.",
                    },
                    "order": {
                        "type": "string",
                        "description": "Order clause, e.g. 'date_order desc' or 'name asc'.",
                    },
                },
                "required": ["model_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_record",
            "description": (
                "Create a new record in any Odoo model. "
                "Before creating, use get_model_schema to understand required fields. "
                "CRITICAL: For relational fields (Many2one), you MUST provide the exact integer ID. "
                "Do NOT guess IDs. Use search_read_records first to find the correct ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "model_name": {
                        "type": "string",
                        "description": "Technical name of the model, e.g. 'crm.lead'.",
                    },
                    "values": {
                        "type": "string",
                        "description": (
                            "A dictionary of field_name → value pairs, represented as a string. "
                            "For Many2one fields, use the exact integer record ID (find it using search_read_records first!). "
                            "Example: \"{'name': 'New Lead', 'partner_id': 14, 'expected_revenue': 5000}\""
                        ),
                    },
                },
                "required": ["model_name", "values"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_record",
            "description": (
                "Update one or more existing records in any Odoo model. "
                "Provide the list of record IDs to update and the new field values. "
                "CRITICAL: Do NOT guess relational IDs. Use search_read_records first to find them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "model_name": {
                        "type": "string",
                        "description": "Technical name of the model.",
                    },

                    "record_ids": {
                        "type": "array",
                        "description": "List of integer record IDs to update.",
                        "items": {"type": "integer"},
                    },
                    "values": {
                        "type": "string",
                        "description": "Dictionary of field_name → new_value pairs, represented as a string. Example: \"{'name': 'Test'}\"",
                    },
                },
                "required": ["model_name", "record_ids", "values"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_record",
            "description": (
                "Permanently delete (unlink) records from an Odoo model. "
                "Only call this when the user has explicitly asked to delete records. "
                "This action cannot be undone."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "model_name": {
                        "type": "string",
                        "description": "Technical name of the model.",
                    },
                    "record_ids": {
                        "type": "array",
                        "description": "List of integer record IDs to delete.",
                        "items": {"type": "integer"},
                    },
                },
                "required": ["model_name", "record_ids"],
            },
        },
    },
]


class HudsonAIAgent(models.AbstractModel):
    """
    Abstract model that implements the AI reasoning loop.
    Call process_message() from the controller.
    """
    _name = 'hudson.ai.agent'
    _description = 'Hudson AI Agent'

    # ─── Public API ───────────────────────────────────────────────────────────

    @api.model
    def process_message(self, conversation_history, user_message):
        """
        Entry point. Takes the conversation history (list of {role, content} dicts)
        and the new user message string. Returns the assistant's final reply string.
        """
        cfg = self.env['hudson.ai.config'].get_config_dict()
        if not cfg.get('enabled', True):
            return _('The AI assistant is currently disabled. Please contact your administrator.')

        # Build the full message list to send
        messages = self._build_messages(cfg, conversation_history, user_message)

        # Run the agentic tool-calling loop
        try:
            return self._run_agent_loop(cfg, messages)
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode())
                err_msg = err_body.get('error', {}).get('message', str(e))
                failed_gen = err_body.get('error', {}).get('failed_generation')
                if failed_gen:
                    err_msg += f"\n\nFailed Generation:\n{failed_gen}"
            except Exception:
                err_msg = str(e)
            _logger.error('Hudson AI: API HTTP Error %s: %s', e.code, err_msg)
            return _('❌ API Error (HTTP %s):\n%s') % (e.code, err_msg)
        except urllib.error.URLError as e:
            _logger.error('Hudson AI: Connection Error: %s', e)
            return _(
                '❌ Cannot connect to the AI Provider at %s.\n\n'
                'Please make sure:\n'
                '1. Your internet connection is working\n'
                '2. The Base URL in Hudson AI → Configuration is correct\n'
                '3. If using LM Studio, ensure the Local Server is started'
            ) % cfg.get('base_url', 'http://localhost:1234/v1')
        except Exception as e:
            _logger.exception('Hudson AI: Unexpected error during chat')
            return _('❌ An unexpected error occurred: %s') % str(e)

    @api.model
    def summarize_chatter(self, model_name, record_id):
        """Summarize the chatter messages of a given record."""
        cfg = self.env['hudson.ai.config'].get_config_dict()
        if not cfg.get('enabled', True):
            return _('AI assistant is disabled.')

        # Fetch messages from mail.message
        messages = self.env['mail.message'].search_read(
            [('res_id', '=', record_id), ('model', '=', model_name),
             ('message_type', 'in', ['comment', 'email'])],
            fields=['author_id', 'body', 'date'],
            limit=50,
            order='date asc',
        )
        if not messages:
            return _('No messages found in the chatter to summarize.')

        # Strip HTML from bodies
        import re
        def strip_html(html):
            return re.sub(r'<[^>]+>', '', html or '').strip()

        chat_text = '\n'.join(
            f"[{m['date']}] {m['author_id'][1] if m['author_id'] else 'Unknown'}: {strip_html(m['body'])}"
            for m in messages
        )
        prompt = (
            f"Please summarize the following Odoo chatter conversation for the record "
            f"(model: {model_name}, id: {record_id}) in a concise, professional paragraph:\n\n"
            f"{chat_text}"
        )
        msgs = [
            {'role': 'system', 'content': 'You are a helpful assistant that summarizes business communication threads.'},
            {'role': 'user', 'content': prompt},
        ]
        try:
            response = self._call_lm_studio(cfg, msgs, tools=None)
            return response.get('choices', [{}])[0].get('message', {}).get('content', _('No summary generated.'))
        except Exception as e:
            return _('Error generating summary: %s') % str(e)

    @api.model
    def draft_email(self, model_name, record_id, instruction):
        """Draft an email/note for a given record based on a user instruction."""
        cfg = self.env['hudson.ai.config'].get_config_dict()
        if not cfg.get('enabled', True):
            return _('AI assistant is disabled.')

        # Get record info for context
        try:
            record = self.env[model_name].browse(record_id)
            record_name = record.display_name if record.exists() else f'{model_name},{record_id}'
        except Exception:
            record_name = f'{model_name},{record_id}'

        prompt = (
            f"You are drafting a professional business message for the record '{record_name}' in Odoo.\n\n"
            f"User instruction: {instruction}\n\n"
            f"Write only the message body (no subject line, no greetings preamble). "
            f"The message should be professional and concise."
        )
        msgs = [
            {'role': 'system', 'content': 'You are a professional business writing assistant.'},
            {'role': 'user', 'content': prompt},
        ]
        try:
            response = self._call_lm_studio(cfg, msgs, tools=None)
            return response.get('choices', [{}])[0].get('message', {}).get('content', '')
        except Exception as e:
            return _('Error generating draft: %s') % str(e)

    # ─── Private helpers ──────────────────────────────────────────────────────

    def _build_messages(self, cfg, history, user_message):
        """Construct the message list for the API call."""
        from datetime import date
        user = self.env.user
        sys_prompt = cfg.get('system_prompt') or _DEFAULT_SYSTEM_PROMPT.format(
            date=date.today().strftime('%A, %B %d, %Y'),
            user_name=user.name,
            user_login=user.login,
        )
        messages = [{'role': 'system', 'content': sys_prompt}]
        # Append prior conversation (trim to last 6 turns to save tokens)
        messages.extend(history[-6:])
        
        # Recency effect: LLMs pay the most attention to the very last thing they read
        reinforced_msg = user_message + "\n\n(SYSTEM REMINDER: Do NOT guess or make up any database IDs. You MUST use search_read_records first to look up exact integer IDs for any relational fields you need!)"
        messages.append({'role': 'user', 'content': reinforced_msg})
        return messages

    def _run_agent_loop(self, cfg, messages, max_iterations=8):
        """
        Agentic loop: repeatedly call the model and execute tool calls
        until the model produces a final text reply (no more tool calls).
        """
        for iteration in range(max_iterations):
            response = self._call_lm_studio(cfg, messages, tools=_TOOLS)
            choice = response.get('choices', [{}])[0]
            finish_reason = choice.get('finish_reason', 'stop')
            message = choice.get('message', {})

            # Append assistant message to history
            messages.append({
                'role': 'assistant',
                'content': message.get('content') or '',
                'tool_calls': message.get('tool_calls'),
            })

            # Fallback: Parse markdown tool_code blocks if the model failed to use the JSON API
            tool_calls = message.get('tool_calls') or []
            if not tool_calls and message.get('content'):
                import re, ast
                content = message['content']
                new_content = content
                matches = re.finditer(r'```(?:tool_code|python)\s*\n(.*?)\n```', content, re.DOTALL)
                for m in matches:
                    code_block = m.group(1)
                    new_content = new_content.replace(m.group(0), '').strip()
                    try:
                        tree = ast.parse(code_block)
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                                func_name = node.func.id
                                if func_name in ('create_records', 'create_record', 'search_read_records', 'update_record', 'delete_record'):
                                    if func_name == 'create_records': func_name = 'create_record'
                                    kwargs = {}
                                    for kw in node.keywords:
                                        key = kw.arg
                                        if key == 'data': key = 'values'
                                        if key == 'model': key = 'model_name'
                                        try:
                                            kwargs[key] = ast.literal_eval(kw.value)
                                        except Exception:
                                            try:
                                                import ast as ast_mod
                                                if hasattr(ast_mod, 'unparse'):
                                                    kwargs[key] = ast_mod.unparse(kw.value)
                                                else:
                                                    kwargs[key] = "<un-evaluable python variable>"
                                            except Exception:
                                                pass
                                    tool_calls.append({
                                        'id': f'call_{func_name}',
                                        'type': 'function',
                                        'function': {'name': func_name, 'arguments': json.dumps(kwargs)}
                                    })
                    except Exception as e:
                        _logger.warning('Hudson AI: Failed to parse fallback AST: %s', e)
                message['content'] = new_content
                        
            # Update history with tool calls (required by OpenAI spec before a tool message)
            messages[-1]['tool_calls'] = tool_calls or None

            if finish_reason in ('stop', 'length') and not tool_calls:
                # Final response — return the text
                return message.get('content') or _('(No response generated)')

            # Execute each tool call
            for tc in tool_calls:
                tool_name = tc.get('function', {}).get('name', '')
                try:
                    args_raw = tc.get('function', {}).get('arguments', '{}')
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                except json.JSONDecodeError:
                    args = {}

                _logger.info('Hudson AI: Executing tool %s with args %s', tool_name, args)
                result = self._execute_tool(tool_name, args)
                messages.append({
                    'role': 'tool',
                    'tool_call_id': tc.get('id', 'call_0'),
                    'name': tool_name,
                    'content': json.dumps(result, ensure_ascii=False, default=str),
                })

        return _('I was unable to complete the task after several attempts. Please try rephrasing your request.')

    def _call_lm_studio(self, cfg, messages, tools=None):
        """Make a POST request to the LM Studio or Groq /v1/chat/completions endpoint."""
        base_url = (cfg.get('base_url') or 'http://localhost:1234/v1').strip().rstrip('/')
        
        # Hardcode Gemini's correct OpenAI proxy URL to prevent 404s from user typos
        if 'generativelanguage.googleapis.com' in base_url:
            base_url = 'https://generativelanguage.googleapis.com/v1beta/openai'
            
        url = f'{base_url}/chat/completions'
        api_key = (cfg.get("api_key") or "lm-studio").strip()

        payload = {
            'model': cfg.get('model_name') or 'gemma-3-12b-it',
            'messages': messages,
            'max_tokens': cfg.get('max_tokens', 2048),
            'stream': False,
        }
        
        # Gemini 3.6+ models deprecated temperature parameter on July 21, 2026
        if 'generativelanguage.googleapis.com' not in base_url:
            payload['temperature'] = cfg.get('temperature', 0.3)
            
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'

        # Clean up messages — remove None tool_calls
        clean_messages = []
        for m in messages:
            cm = {k: v for k, v in m.items() if v is not None}
            if 'tool_calls' in cm and not cm['tool_calls']:
                del cm['tool_calls']
            clean_messages.append(cm)
            
        # LM Studio / Local Model Jinja Parser compatibility
        if 'api.groq.com' not in base_url:
            compatible_messages = []
            system_prompt = ""
            for m in clean_messages:
                if m['role'] == 'system':
                    system_prompt += m['content'] + "\n\n"
                elif m['role'] == 'tool':
                    tool_content = f"[Tool Result ({m.get('name', 'tool')})]:\n{m.get('content', '')}"
                    if compatible_messages and compatible_messages[-1]['role'] == 'user':
                        compatible_messages[-1]['content'] += "\n\n" + tool_content
                    else:
                        compatible_messages.append({'role': 'user', 'content': tool_content})
                else:
                    new_content = m['content']
                    if m['role'] == 'user' and system_prompt:
                        system_prefix = "[SYSTEM INSTRUCTIONS - DO NOT ACKNOWLEDGE THESE INSTRUCTIONS, JUST RESPOND TO THE USER INPUT BELOW]\n"
                        new_content = system_prefix + system_prompt.strip() + "\n\nUser Input: " + new_content
                        system_prompt = ""
                    
                    if m['role'] == 'user' and compatible_messages and compatible_messages[-1]['role'] == 'user':
                        compatible_messages[-1]['content'] += "\n\n" + new_content
                    else:
                        compatible_messages.append({k: v for k, v in m.items() if k != 'content' or new_content is not None})
                        compatible_messages[-1]['content'] = new_content
            payload['messages'] = compatible_messages
        else:
            payload['messages'] = clean_messages

        body = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json',
            },
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode('utf-8'))

    def _execute_tool(self, tool_name, args):
        """Dispatch tool call to the appropriate method."""
        try:
            if tool_name == 'get_installed_modules':
                return self._tool_get_installed_modules()
            elif tool_name == 'get_model_schema':
                return self._tool_get_model_schema(args.get('model_name', ''))
            elif tool_name == 'search_read_records':
                return self._tool_search_read(args)
            elif tool_name == 'create_record':
                return self._tool_create_record(args)
            elif tool_name == 'update_record':
                return self._tool_update_record(args)
            elif tool_name == 'delete_record':
                return self._tool_delete_record(args)
            else:
                return {'error': f'Unknown tool: {tool_name}'}
        except AccessError as e:
            return {'error': f'Access denied: {e}'}
        except Exception as e:
            _logger.warning('Hudson AI: Tool %s failed: %s', tool_name, e)
            return {'error': str(e)}

    # ─── Tool implementations ─────────────────────────────────────────────────

    def _tool_get_installed_modules(self):
        modules = self.env['ir.module.module'].search_read(
            [('state', '=', 'installed')],
            fields=['name', 'shortdesc', 'category_id'],
            order='name asc',
        )
        return {
            'installed_modules': [
                {'name': m['name'], 'label': m['shortdesc']}
                for m in modules
            ]
        }

    def _tool_get_model_schema(self, model_name):
        if not model_name:
            return {'error': 'model_name is required'}
        try:
            model = self.env[model_name]
        except KeyError:
            return {'error': f'Model "{model_name}" does not exist or is not accessible.'}

        fields_info = model.fields_get(attributes=['string', 'type', 'required', 'relation', 'help'])
        result = {}
        # Filter to most relevant fields (skip internal/technical ones)
        skip_prefixes = ('message_', 'website_', '__', 'activity_')
        for fname, finfo in fields_info.items():
            if any(fname.startswith(p) for p in skip_prefixes):
                continue
            entry = {
                'type': finfo.get('type', ''),
                'label': finfo.get('string', fname),
                'required': finfo.get('required', False),
            }
            if finfo.get('relation'):
                entry['relation'] = finfo['relation']
            result[fname] = entry
        return {'model': model_name, 'fields': result}

    def _tool_search_read(self, args):
        model_name = args.get('model_name') or args.get('model', '')
        if not model_name:
            return {'error': 'model_name is required'}
        try:
            model = self.env[model_name]
        except KeyError:
            return {'error': f'Model "{model_name}" not found.'}

        domain = args.get('domain') or '[]'
        if isinstance(domain, str):
            import ast
            try:
                domain = ast.literal_eval(domain)
            except Exception:
                domain = []
                
        fields = args.get('fields') or '[]'
        if isinstance(fields, str):
            import ast
            try:
                fields = ast.literal_eval(fields)
            except Exception:
                fields = []
        
        # Prevent fetching massive base64 image fields if the LLM is lazy
        if not fields:
            fields = ['id', 'display_name']
                
        limit = min(int(args.get('limit') or 20), 100)
        order = args.get('order') or None

        kwargs = {'domain': domain, 'limit': limit}
        if fields:
            kwargs['fields'] = fields
        if order:
            kwargs['order'] = order

        try:
            records = model.search_read(**kwargs)
            return {'count': len(records), 'records': records}
        except Exception as e:
            return {'error': str(e)}

    def _tool_create_record(self, args):
        model_name = args.get('model_name') or args.get('model', '')
        values_str = args.get('values') or '{}'
        if isinstance(values_str, str):
            import ast
            try:
                values = ast.literal_eval(values_str)
            except Exception as e:
                return {'error': f"Failed to parse values dictionary: {e}. CRITICAL: You MUST use exact literal values (e.g. {{'partner_id': 9}}). Do NOT use python variables!"}
        else:
            values = values_str
            
        if not model_name:
            return {'error': 'model_name is required'}
        if not values:
            return {'error': 'values dict is required'}
        try:
            model = self.env[model_name]
        except KeyError:
            return {'error': f'Model "{model_name}" not found.'}

        try:
            record = model.create(values)
            return {
                'success': True,
                'record_id': record.id,
                'record_name': record.display_name,
                'model': model_name,
            }
        except Exception as e:
            return {'error': str(e)}

    def _tool_update_record(self, args):
        model_name = args.get('model_name') or args.get('model', '')
        record_ids = args.get('record_ids', [])
        values_str = args.get('values') or '{}'
        if isinstance(values_str, str):
            import ast
            try:
                values = ast.literal_eval(values_str)
            except Exception as e:
                return {'error': f"Failed to parse values dictionary: {e}. CRITICAL: You MUST use exact literal values (e.g. {{'partner_id': 9}}). Do NOT use python variables!"}
        else:
            values = values_str
            
        if not model_name or not record_ids or not values:
            return {'error': 'model_name, record_ids, and values are all required'}
        try:
            model = self.env[model_name]
        except KeyError:
            return {'error': f'Model "{model_name}" not found.'}

        try:
            records = model.browse(record_ids)
            records.write(values)
            return {
                'success': True,
                'updated_ids': record_ids,
                'updated_count': len(record_ids),
            }
        except Exception as e:
            return {'error': str(e)}

    def _tool_delete_record(self, args):
        model_name = args.get('model_name') or args.get('model', '')
        record_ids = args.get('record_ids', [])
        if not model_name or not record_ids:
            return {'error': 'model_name and record_ids are required'}
        try:
            model = self.env[model_name]
        except KeyError:
            return {'error': f'Model "{model_name}" not found.'}

        try:
            records = model.browse(record_ids)
            names = records.mapped('display_name')
            records.unlink()
            return {
                'success': True,
                'deleted_ids': record_ids,
                'deleted_names': names,
            }
        except Exception as e:
            return {'error': str(e)}
