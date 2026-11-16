"""HTTP client for the Odoo endpoints (stdlib only). See API.md for the contract."""
import getpass
import json
import logging
import platform
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

from . import VERSION

_logger = logging.getLogger(__name__)

PAIR_PATH = "/api/activity/pair"
INGEST_PATH = "/api/activity/ingest"


class ApiError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Unauthorized(ApiError):
    pass


def normalize_url(url: str):
    """Returns (base_url, database). The database can be given as ?db=NAME,
    which is needed when the Odoo server hosts several databases."""
    url = (url or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ApiError(f"Invalid server URL: {url!r}")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        _logger.warning("Server %s uses plain HTTP: the device token is sent unencrypted", url)
    database = (parse_qs(parsed.query).get("db") or [""])[0]
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
    return base, database


def device_info(device_uid: str) -> dict:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - getuser can fail in odd environments
        user = ""
    return {
        "device_uid": device_uid,
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "os_user": user,
        "agent_version": VERSION,
    }


_SSL_CONTEXT = None


def _ssl_context():
    """System trust store (Windows store / corporate CAs) plus the certifi bundle.
    A frozen Python on macOS often finds no system CA file at all, which would make
    every HTTPS connection to a hosted server fail certificate verification."""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        ctx = ssl.create_default_context()
        try:
            import certifi
            ctx.load_verify_locations(certifi.where())
        except (ImportError, OSError):
            _logger.debug("certifi not available, using the system trust store only")
        _SSL_CONTEXT = ctx
    return _SSL_CONTEXT


def _post(url, body, token=None, database=None, timeout=20) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": f"HudsonActivityAgent/{VERSION}",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if database:
        headers["X-Odoo-Database"] = database
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:500].decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", detail)
        except ValueError:
            pass
        if e.code in (401, 403):
            raise Unauthorized(detail or "Unauthorized", e.code) from None
        raise ApiError(f"HTTP {e.code}: {detail}", e.code) from None
    except (urllib.error.URLError, OSError) as e:
        raise ApiError(f"Cannot reach server: {getattr(e, 'reason', e)}") from None
    try:
        return json.loads(raw or b"{}")
    except ValueError:
        raise ApiError("Server returned invalid JSON") from None


class ApiClient:
    def __init__(self, config):
        self.config = config

    def pair(self, server_url: str, code: str) -> dict:
        server_url, database = normalize_url(server_url)
        body = dict(device_info(self.config.device_uid), code=code.strip())
        resp = _post(server_url + PAIR_PATH, body, database=database)
        if not resp.get("token"):
            raise ApiError(resp.get("error") or "Pairing failed")
        with self.config._lock:
            self.config.server_url = server_url
            self.config.database = resp.get("database") or database
            self.config.token = resp["token"]
            self.config.employee_name = resp.get("employee") or ""
            self.config.save()
        self.config.update_settings(resp.get("config") or {})
        return resp

    def ingest(self, spans: list) -> dict:
        body = {
            "device_uid": self.config.device_uid,
            "agent_version": VERSION,
            "spans": spans,
        }
        return _post(self.config.server_url + INGEST_PATH, body, token=self.config.token,
                     database=self.config.database)
