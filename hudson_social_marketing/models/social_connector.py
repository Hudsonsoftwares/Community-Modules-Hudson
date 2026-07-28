# Part of Hudson Community. See LICENSE file for full copyright and licensing details.

import json
import logging
import urllib.request
import urllib.error
import urllib.parse

from odoo import models, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_REMOTE_URL = 'https://hudson-social.odoo.com'
DEFAULT_REMOTE_DB = 'hudson-social'
DEFAULT_REMOTE_EMAIL = 'nandusaji20012001@gmail.com'
DEFAULT_API_KEY = '04faf49029b6972ebea6c145572b4060bf372e05'


class SocialConnector(models.AbstractModel):
    """
    Mixin that provides JSON-RPC helpers to communicate with a remote Odoo
    instance (Odoo Enterprise / Odoo SaaS) that has Social Marketing installed.

    Usage:
        uid = self._social_authenticate()
        records = self._social_execute('social.post', 'search_read', [[]], fields=[...])
    """

    _name = 'hudson.social.connector'
    _description = 'Social Marketing — Remote Connector'

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _get_social_config(self):
        """Return (url, db, email, api_key) from ir.config_parameter."""
        ICP = self.env['ir.config_parameter'].sudo()
        url = ICP.get_param('hudson_social.remote_url', DEFAULT_REMOTE_URL).rstrip('/')
        db = ICP.get_param('hudson_social.remote_db', DEFAULT_REMOTE_DB)
        email = ICP.get_param('hudson_social.remote_email', DEFAULT_REMOTE_EMAIL)
        api_key = ICP.get_param('hudson_social.api_key', DEFAULT_API_KEY)
        return url, db, email, api_key

    # ------------------------------------------------------------------
    # Low-level JSON-RPC
    # ------------------------------------------------------------------

    def _jsonrpc(self, url, payload, timeout=30):
        """
        Send a JSON-RPC request to *url* and return the parsed response dict.
        Raises UserError on network / application errors.
        """
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            raise UserError(
                _("HTTP error %s while calling remote Odoo:") % e.code
                + "\n" + str(e.reason)
            )
        except urllib.error.URLError as e:
            raise UserError(
                _("Cannot reach remote Odoo instance at %s.") % url
                + "\n" + _("Reason: %s") % str(e.reason)
            )
        except Exception as e:
            raise UserError(_("Unexpected error contacting remote Odoo: %s") % str(e))

        if result.get('error'):
            err = result['error']
            msg = err.get('data', {}).get('message') or err.get('message', 'Unknown error')
            raise UserError(_("Remote Odoo error: %s") % msg)

        return result.get('result')

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _social_authenticate(self):
        """
        Authenticate with the remote Odoo instance and return the uid.
        Uses the API key as the password (Odoo 14+ supports this).
        """
        url, db, email, api_key = self._get_social_config()
        endpoint = f"{url}/jsonrpc"
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "id": 1,
            "params": {
                "service": "common",
                "method": "authenticate",
                "args": [db, email, api_key, {}],
            },
        }
        _logger.info("Authenticating with remote Odoo at %s (db: %s, user: %s)", url, db, email)
        uid = self._jsonrpc(endpoint, payload)
        if not uid:
            raise UserError(
                _("Authentication failed for user '%s' on database '%s'.") % (email, db)
                + "\n" + _("Please check the API key and credentials in Settings > Social Marketing.")
            )
        _logger.info("Remote Odoo authentication successful — uid: %s", uid)
        return uid

    # ------------------------------------------------------------------
    # execute_kw wrapper
    # ------------------------------------------------------------------

    def _social_execute(self, model, method, args=None, **kwargs):
        """
        Execute a method on the remote Odoo instance.

        :param model: remote model name (e.g. 'social.post')
        :param method: method name (e.g. 'search_read', 'create', 'write')
        :param args: positional args list (e.g. [[domain]])
        :param kwargs: keyword args (e.g. fields=[...], limit=100)
        :return: result from remote
        """
        url, db, _email, api_key = self._get_social_config()
        uid = self._social_authenticate()
        endpoint = f"{url}/jsonrpc"
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "id": 2,
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [db, uid, api_key, model, method, args or [[]], kwargs],
            },
        }
        _logger.info("Remote call: model=%s method=%s", model, method)
        return self._jsonrpc(endpoint, payload)

    # ------------------------------------------------------------------
    # Convenience read helpers
    # ------------------------------------------------------------------

    def _social_search_read(self, model, domain=None, fields=None, limit=200, order=None):
        kwargs = {'limit': limit}
        if fields:
            kwargs['fields'] = fields
        if order:
            kwargs['order'] = order
        return self._social_execute(model, 'search_read', [domain or []], **kwargs)

    def _social_create(self, model, vals):
        return self._social_execute(model, 'create', [vals])

    def _social_write(self, model, ids, vals):
        return self._social_execute(model, 'write', [ids, vals])

    def _social_unlink(self, model, ids):
        return self._social_execute(model, 'unlink', [ids])

    def _social_check_connection(self):
        """Test connectivity and return a summary string."""
        try:
            uid = self._social_authenticate()
            url, db, email, _api_key = self._get_social_config()
            return True, (
                "Connected to %s" % url
                + "\nDatabase: %s | User UID: %s" % (db, uid)
            )
        except UserError as e:
            return False, str(e)
