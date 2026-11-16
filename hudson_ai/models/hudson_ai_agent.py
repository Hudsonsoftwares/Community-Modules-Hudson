# Part of Hudson Community. See LICENSE file for full copyright and licensing details.
"""Hudson AI agent: a small tool-calling loop over the Odoo ORM.

Everything runs with the current user's access rights. The model only gets
what it asks for through the tools, and every result is kept compact so a
request fits easily within the token limits of free API plans.
"""

import ast
import json
import logging
import re
from datetime import date, datetime

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import html2plaintext, html_sanitize

from .ai_access_rule import LOOKUP_FIELDS
from .ai_provider import chat_completion, get_ai_settings

_logger = logging.getLogger(__name__)

MAX_ITERATIONS = 8
MAX_HISTORY_MESSAGES = 10
MAX_HISTORY_CHARS = 4000
MAX_TOOL_RESULT_CHARS = 6000
MAX_TEXT_VALUE_CHARS = 300
MAX_SEARCH_LIMIT = 50
MAX_FIELDS = 80

SYSTEM_PROMPT = """You are Hudson AI, the assistant built into Odoo for {company}.
Today is {today}. The user is {user}; reply in their language ({lang}).

- Use the tools to read or change data. Never invent records, IDs, amounts or field names.
- Unsure of a model or field name? Use find_models / get_fields first.
- For totals, counts and rankings use aggregate_records instead of reading many records.
- Many2one values need the integer ID: look it up with search_records first.
- If a search finds nothing, retry once with a broader domain (fewer filters, partial name) before saying it does not exist.
- If a tool says data is not available to this user, tell them they do not have access to it. Do not look for other models to get around it.
- Only create or update records when the user asked for it. Never claim success unless the tool returned it.
- Answers are short and in Markdown. Mention record names, not internal IDs."""

RECORD_CONTEXT_PROMPT = """The user is viewing {model_name} "{name}" (model {model}, id {id}).
Main fields: {values}
Latest messages:
{messages}"""
SNAPSHOT_FIELD_TYPES = ('char', 'selection', 'date', 'datetime', 'monetary', 'float', 'integer',
                        'many2one', 'boolean')
MAX_SNAPSHOT_FIELDS = 25

ARTICLE_PROMPT = """You are Hudson AI, writing a document for the knowledge base of {company}.
The author is {user}; today is {today}. Write in the language of the request (default {lang}).

- Return only HTML, no Markdown and no code fences.
- Start with one <h1> title, then use <h2>/<h3>, <p>, <ul>/<ol>, <table>, <strong>, <em>.
- No <html>, <head>, <body>, <style> or <script> tags, no inline styles, no images.
- Write real, specific content for the request. Where facts only the author knows are
  needed (names, dates, figures), leave a short [placeholder in brackets] instead of inventing them."""

TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'find_models',
            'description': 'Find Odoo models by keyword, e.g. "invoice", "lead", "employee".',
            'parameters': {
                'type': 'object',
                'properties': {'query': {'type': 'string'}},
                'required': ['query'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_fields',
            'description': 'List the fields of a model (name: type). Optionally filter by keyword.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'model': {'type': 'string', 'description': "e.g. 'sale.order'"},
                    'query': {'type': 'string', 'description': 'Optional keyword, e.g. "date"'},
                },
                'required': ['model'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'search_records',
            'description': 'Search records and read some of their fields.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'model': {'type': 'string'},
                    'domain': {
                        'type': 'array',
                        'items': {},
                        'description': ("Odoo domain, e.g. [[\"name\", \"ilike\", \"azure\"], "
                                        "[\"date_order\", \">=\", \"2026-01-01\"]]. Use ilike for names."),
                    },
                    'fields': {'type': 'array', 'items': {'type': 'string'}},
                    'limit': {'type': 'integer', 'description': 'Default 10, max 50'},
                    'order': {'type': 'string', 'description': "e.g. 'amount_total desc'"},
                },
                'required': ['model', 'fields'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'aggregate_records',
            'description': 'Count / sum / average records, optionally grouped (e.g. sales per customer).',
            'parameters': {
                'type': 'object',
                'properties': {
                    'model': {'type': 'string'},
                    'domain': {'type': 'array', 'items': {}},
                    'groupby': {
                        'type': 'array', 'items': {'type': 'string'},
                        'description': "e.g. ['partner_id'] or ['date_order:month']",
                    },
                    'aggregates': {
                        'type': 'array', 'items': {'type': 'string'},
                        'description': "e.g. ['__count', 'amount_total:sum']",
                    },
                    'order': {'type': 'string', 'description': "e.g. 'amount_total:sum desc'"},
                    'limit': {'type': 'integer'},
                },
                'required': ['model', 'aggregates'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'create_record',
            'description': 'Create a record. Use integer IDs for relational fields.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'model': {'type': 'string'},
                    'values': {'type': 'object'},
                },
                'required': ['model', 'values'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'update_records',
            'description': 'Write new values on existing records.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'model': {'type': 'string'},
                    'ids': {'type': 'array', 'items': {'type': 'integer'}},
                    'values': {'type': 'object'},
                },
                'required': ['model', 'ids', 'values'],
            },
        },
    },
]

SKIPPED_FIELD_PREFIXES = ('message_', 'activity_', 'website_message', '__')
SKIPPED_FIELDS = {'id', 'display_name', 'create_uid', 'write_uid', 'write_date', 'access_token',
                  'access_url', 'access_warning'}


def _parse(value, default):
    """Models sometimes send JSON (or Python literals) as strings."""
    if not isinstance(value, str):
        return default if value is None else value
    value = value.strip()
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return default


def _compact(value):
    """Make one field value small and JSON-friendly."""
    if isinstance(value, models.BaseModel):
        if not value:
            return False
        if len(value) == 1:
            return [value.id, value.display_name]
        return [[r.id, r.display_name] for r in value[:10]] + (
            [f'... {len(value) - 10} more'] if len(value) > 10 else [])
    if isinstance(value, (date, datetime)):
        return fields.Datetime.to_string(value) if isinstance(value, datetime) else str(value)
    if isinstance(value, bytes):
        return '<binary>'
    if isinstance(value, str) and len(value) > MAX_TEXT_VALUE_CHARS:
        return value[:MAX_TEXT_VALUE_CHARS] + '…'
    if isinstance(value, (list, tuple)) and len(value) > 20:
        return list(value[:20]) + [f'... {len(value) - 20} more']
    return value


class HudsonAIAgent(models.AbstractModel):
    _name = 'hudson.ai.agent'
    _description = 'Hudson AI Agent'

    # ------------------------------------------------------------------ chat

    @api.model
    def chat(self, user_message, history=None, record=None):
        """Answer a chat message. Returns {'reply': str, 'records': [{model, id, name}]}."""
        cfg = get_ai_settings(self.env)
        state = {'touched': [], 'scope': self.env['hudson.ai.access.rule']._get_scope()}
        messages = [{'role': 'system', 'content': self._system_prompt(record, state)}]
        for msg in (history or [])[-MAX_HISTORY_MESSAGES:]:
            if msg.get('role') in ('user', 'assistant') and msg.get('content'):
                messages.append({'role': msg['role'],
                                 'content': str(msg['content'])[:MAX_HISTORY_CHARS]})
        messages.append({'role': 'user', 'content': user_message[:MAX_HISTORY_CHARS]})

        for _iteration in range(MAX_ITERATIONS):
            answer = self._call(cfg, messages, 'chat', tools=TOOLS)
            tool_calls = answer.get('tool_calls') or []
            if not tool_calls:
                return {'reply': answer.get('content') or _('(No answer)'), 'records': state['touched']}
            messages.append({'role': 'assistant', 'content': answer.get('content') or '',
                             'tool_calls': tool_calls})
            for call in tool_calls:
                name = call.get('function', {}).get('name', '')
                args = _parse(call.get('function', {}).get('arguments'), {})
                result = self._run_tool(name, args if isinstance(args, dict) else {}, state)
                content = json.dumps(result, ensure_ascii=False, default=str)
                if len(content) > MAX_TOOL_RESULT_CHARS:
                    content = content[:MAX_TOOL_RESULT_CHARS] + (
                        '... [truncated: ask for fewer fields or records]')
                messages.append({'role': 'tool', 'tool_call_id': call.get('id') or name,
                                 'content': content})
        return {'reply': _('I could not finish this request. Please rephrase it or split it '
                           'into smaller steps.'), 'records': state['touched']}

    def _call(self, cfg, messages, feature, tools=None):
        answer, usage = chat_completion(cfg, messages, tools)
        self.env['hudson.ai.usage']._log(usage, feature, model=cfg['model'])
        return answer

    def _system_prompt(self, record, state):
        user = self.env.user
        prompt = SYSTEM_PROMPT.format(
            company=self.env.company.name,
            today=fields.Date.context_today(self).strftime('%A %d %B %Y'),
            user=user.name,
            lang=user.lang or 'en_US',
        )
        rec = self._get_context_record(record, state['scope'])
        if rec:
            prompt += '\n\n' + RECORD_CONTEXT_PROMPT.format(
                model_name=self.env['ir.model']._get(rec._name).name,
                name=rec.display_name, model=rec._name, id=rec.id,
                values=json.dumps(self._record_snapshot(rec), ensure_ascii=False, default=str),
                messages=self._thread_text(rec, limit=5, chars=2000) or '(none)')
        return prompt

    def _record_snapshot(self, record):
        """Small dict of the record's filled-in business fields (saves tool calls)."""
        values = {}
        for name, field in record._fields.items():
            if (field.type not in SNAPSHOT_FIELD_TYPES or not field.store or field.groups
                    or name in SKIPPED_FIELDS or name.startswith(SKIPPED_FIELD_PREFIXES)
                    or name in ('create_date', 'company_id', 'currency_id')):
                continue
            try:
                value = record[name]
            except AccessError:
                continue
            if not value:
                continue  # empty values and False flags are only noise
            values[field.string] = _compact(value)
            if len(values) >= MAX_SNAPSHOT_FIELDS:
                break
        return values

    def _get_context_record(self, record, scope):
        """The record the user is looking at, if the AI may read that kind of record."""
        if not record or not record.get('model') or not record.get('id'):
            return None
        if record['model'] not in scope['full']:
            return None
        rec = self.env[record['model']].browse(int(record['id'])).exists()
        try:
            rec.check_access('read')
        except AccessError:
            return None
        return rec or None

    # ----------------------------------------------------------------- tools

    def _run_tool(self, name, args, state):
        handler = {
            'find_models': self._tool_find_models,
            'get_fields': self._tool_get_fields,
            'search_records': self._tool_search_records,
            'aggregate_records': self._tool_aggregate_records,
            'create_record': self._tool_create_record,
            'update_records': self._tool_update_records,
        }.get(name)
        if not handler:
            return {'error': f'Unknown tool {name}'}
        _logger.info('Hudson AI tool %s %s', name, args)
        try:
            # A failed write must not abort the transaction of the whole chat request.
            with self.env.cr.savepoint():
                return handler(args, state)
        except AccessError as e:
            return {'error': f'Access denied: {e}'}
        except Exception as e:  # noqa: BLE001 - errors are reported to the model
            return {'error': str(e)}

    def _model(self, args, state, lookup_ok=False):
        """Return the model named in `args` if the user's AI scope allows it."""
        model_name = args.get('model') or args.get('model_name') or ''
        scope = state['scope']
        if model_name in scope['full'] or (lookup_ok and model_name in scope['lookup']):
            return self.env[model_name]
        if model_name in self.env and model_name in scope['lookup']:
            raise AccessError(f'You can only look up "{model_name}" records by name (search_records).')
        if model_name in self.env:
            raise AccessError(f'"{model_name}" data is not available to this user through the AI.')
        raise UserError(f'Unknown model "{model_name}". Use find_models.')

    def _check_path(self, model, path, scope, allow_lookup=False):
        """A field path used in a domain / groupby must stay within the AI scope.
        Only domains may end on the name of a lookup model (to find a record by name)."""
        current = model
        parts = path.split('.')
        for index, part in enumerate(parts):
            field = current._fields.get(part)
            if field is None:
                raise UserError(f'Unknown field "{part}" on {current._name}.')
            if field.relational and index < len(parts) - 1:
                if field.comodel_name in scope['full']:
                    current = self.env[field.comodel_name]
                    continue
                if (allow_lookup and field.comodel_name in scope['lookup']
                        and index == len(parts) - 2 and parts[-1] in LOOKUP_FIELDS):
                    return
                raise AccessError(f'Filtering on "{field.comodel_name}" data is not available '
                                  'to this user through the AI.')

    def _check_domain(self, model, domain, scope, lookup=False):
        if not isinstance(domain, (list, tuple)):
            raise UserError('domain must be a list')
        for leaf in domain:
            if not (isinstance(leaf, (list, tuple)) and len(leaf) == 3 and isinstance(leaf[0], str)):
                continue
            path, operator, value = leaf
            if lookup and path.split('.')[0] not in LOOKUP_FIELDS:
                raise AccessError(f'"{model._name}" records can only be searched by name.')
            self._check_path(model, path, scope, allow_lookup=True)
            if operator in ('any', 'not any') and isinstance(value, (list, tuple)):
                field = model._fields[path.split('.')[0]]
                self._check_domain(self.env[field.comodel_name], value, scope)
        return list(domain)

    def _tool_find_models(self, args, state):
        query = (args.get('query') or '').strip()
        found = self.env['ir.model'].sudo().search(
            [('transient', '=', False), ('model', 'in', list(state['scope']['full'])),
             '|', ('model', 'ilike', query), ('name', 'ilike', query)], limit=12)
        return ([{'model': m.model, 'name': m.name} for m in found]
                or {'error': f'No model matches "{query}" for this user.'})

    def _tool_get_fields(self, args, state):
        model = self._model(args, state)
        query = (args.get('query') or '').lower()
        result = {}
        for name, info in model.fields_get(
                attributes=['string', 'type', 'relation', 'required', 'selection', 'store']).items():
            if name in SKIPPED_FIELDS or name.startswith(SKIPPED_FIELD_PREFIXES):
                continue
            if info['type'] == 'binary':
                continue
            if query and query not in name.lower() and query not in (info['string'] or '').lower():
                continue
            desc = info['type']
            if info.get('relation'):
                desc += f"({info['relation']})"
            if info.get('selection'):
                desc += '[' + ','.join(str(key) for key, _label in info['selection'][:12]) + ']'
            if info.get('required'):
                desc += ' required'
            if not info.get('store'):
                desc += ' computed'
            result[name] = f"{info['string']}: {desc}"
            if len(result) >= MAX_FIELDS:
                result['...'] = 'more fields exist, pass a query to filter'
                break
        return {'model': model._name, 'fields': result}

    def _tool_search_records(self, args, state):
        model = self._model(args, state, lookup_ok=True)
        lookup = model._name not in state['scope']['full']
        domain = self._check_domain(model, _parse(args.get('domain'), []), state['scope'], lookup=lookup)
        if lookup:
            field_names = ['display_name']
            order = None
        else:
            field_names = [f for f in _parse(args.get('fields'), []) if f in model._fields]
            field_names = field_names or ['display_name']
            order = args.get('order') or None
        limit = max(1, min(int(args.get('limit') or 10), MAX_SEARCH_LIMIT))
        records = model.search(domain, limit=limit, order=order)
        total = len(records) if len(records) < limit else model.search_count(domain)
        rows = []
        for record in records:
            row = {'id': record.id}
            for name in field_names:
                try:
                    row[name] = _compact(record[name])
                except AccessError:
                    row[name] = '<no access>'
            rows.append(row)
        return {'total': total, 'records': rows}

    def _tool_aggregate_records(self, args, state):
        model = self._model(args, state)
        scope = state['scope']
        domain = self._check_domain(model, _parse(args.get('domain'), []), scope)
        groupby = _parse(args.get('groupby'), [])
        aggregates = _parse(args.get('aggregates'), []) or ['__count']
        for spec in groupby:
            self._check_path(model, str(spec).split(':')[0], scope)
        for spec in aggregates:
            if spec != '__count':
                self._check_path(model, str(spec).split(':')[0], scope)
        limit = max(1, min(int(args.get('limit') or 20), MAX_SEARCH_LIMIT))
        groups = model.read_group(domain, groupby, aggregates,
                                  order=args.get('order') or None, limit=limit)
        keys = list(groupby) + list(aggregates)
        return {'groups': [{key: _compact(val) for key, val in zip(keys, group)}
                           for group in groups]}

    def _tool_create_record(self, args, state):
        model = self._model(args, state)
        values = _parse(args.get('values'), {})
        if not isinstance(values, dict) or not values:
            return {'error': 'values must be a non-empty object'}
        record = model.create(values)
        state['touched'].append({'model': model._name, 'id': record.id, 'name': record.display_name})
        return {'created': {'id': record.id, 'name': record.display_name}}

    def _tool_update_records(self, args, state):
        model = self._model(args, state)
        values = _parse(args.get('values'), {})
        ids = [int(i) for i in _parse(args.get('ids'), [])]
        records = model.browse(ids).exists()
        if not records or not isinstance(values, dict) or not values:
            return {'error': 'Give existing record ids and a non-empty values object.'}
        records.write(values)
        for record in records[:10]:
            state['touched'].append({'model': model._name, 'id': record.id, 'name': record.display_name})
        return {'updated': [{'id': r.id, 'name': r.display_name} for r in records]}

    # --------------------------------------------------------------- chatter

    def _chatter_record(self, model_name, record_id):
        scope = self.env['hudson.ai.access.rule']._get_scope()
        record = self._get_context_record({'model': model_name, 'id': record_id}, scope)
        if not record:
            raise UserError(_('Hudson AI is not available for this record with your access rights.'))
        return record

    @api.model
    def summarize_record(self, model_name, record_id):
        """Summarize the discussion of a record."""
        record = self._chatter_record(model_name, record_id)
        thread = self._thread_text(record, limit=40, chars=12000)
        if not thread:
            return _('There is no discussion on this record yet.')
        prompt = (
            f'Summarize the discussion on {record.display_name} ({record._description}). '
            'Give the key points as bullets, then any open questions or next steps. Be brief.\n\n'
            + thread)
        return self._complete(prompt, 'summarize')

    @api.model
    def draft_message(self, model_name, record_id, instruction):
        """Draft a message for a record."""
        record = self._chatter_record(model_name, record_id)
        thread = self._thread_text(record, limit=6, chars=3000)
        prompt = (
            f'You are {self.env.user.name} from {self.env.company.name}. Write a short, '
            f'professional message to post on {record.display_name} ({record._description}), '
            f'for this request: {instruction}\n'
            f'Sign as {self.env.user.name}, {self.env.company.name}. '
            'Return only the message text, ready to send.'
            + (f'\n\nRecent discussion for context:\n{thread}' if thread else ''))
        return self._complete(prompt, 'draft')

    @api.model
    def write_article(self, instruction):
        """Write a document about `instruction`. Returns {'title': str, 'html': str}.

        Used by other apps (e.g. Knowledge) to generate content; it reads no Odoo data.
        """
        instruction = (instruction or '').strip()[:MAX_HISTORY_CHARS]
        if not instruction:
            raise UserError(_('Describe what the article should be about.'))
        cfg = get_ai_settings(self.env)
        answer = self._call(cfg, [
            {'role': 'system', 'content': ARTICLE_PROMPT.format(
                company=self.env.company.name, user=self.env.user.name,
                today=fields.Date.context_today(self).strftime('%d %B %Y'),
                lang=self.env.user.lang or 'en_US')},
            {'role': 'user', 'content': instruction},
        ], 'write')
        html = (answer.get('content') or '').strip()
        # Models often wrap the answer in a Markdown code fence.
        html = re.sub(r'^```[a-zA-Z]*\s*|\s*```$', '', html).strip()
        if not html:
            raise UserError(_('The AI returned an empty answer. Please try again.'))
        html = html_sanitize(html, sanitize_attributes=True, sanitize_style=True, strip_classes=True)
        title = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
        title = html2plaintext(title.group(1)).strip() if title else ''
        return {'title': title[:120], 'html': str(html)}

    def _thread_text(self, record, limit, chars):
        messages = self.env['mail.message'].search([
            ('model', '=', record._name), ('res_id', '=', record.id),
            ('message_type', 'in', ('comment', 'email', 'email_outgoing')),
        ], order='id desc', limit=limit)
        lines = []
        for message in reversed(messages):
            body = html2plaintext(message.body or '').strip()
            if body:
                author = message.author_id.name or message.email_from or '?'
                lines.append(f'[{message.date:%Y-%m-%d}] {author}: {body[:1500]}')
        text = '\n'.join(lines)
        return text[-chars:]

    def _complete(self, prompt, feature):
        cfg = get_ai_settings(self.env)
        answer = self._call(cfg, [
            {'role': 'system', 'content': f'You are Hudson AI, a business assistant in Odoo. '
                                          f'Reply in {self.env.user.lang or "en_US"}.'},
            {'role': 'user', 'content': prompt},
        ], feature)
        return answer.get('content') or ''
