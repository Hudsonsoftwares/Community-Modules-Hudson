# -*- encoding: utf-8 -*-
"""Callers of a public route, for the tests that check which address the
route counts a caller under and records in the audit trail.

Three callers matter. One goes straight to Odoo, so its address is the
socket peer. One goes straight to Odoo and writes a made up address in
every header a caller could use to claim one. One goes through a trusted
reverse proxy, which Odoo tells apart only in proxy_mode, from the
X-Forwarded-For hop the proxy appends, and only when the proxy also sends
X-Forwarded-Host. The other modules of the suite import this mixin for
their own public routes.
"""
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from odoo.tools import config

from odoo.addons.eh_hr_core.models import rate_limit


class ClientAddressMixin:
    """For an HttpCase."""

    @property
    def peer(self):
        """The socket peer of every request url_open sends."""
        return urlsplit(self.base_url()).hostname

    def forged_headers(self, address):
        """Every header a caller could write to claim ``address``."""
        return {
            'X-Real-IP': address,
            'X-Forwarded-For': address,
            'X-Forwarded-Host': urlsplit(self.base_url()).netloc,
        }

    def proxied_headers(self, forwarded_for):
        """The headers a trusted reverse proxy sends: ``forwarded_for`` is
        what the client wrote followed by the hop the proxy appended."""
        return {
            'X-Forwarded-For': forwarded_for,
            'X-Forwarded-Host': urlsplit(self.base_url()).netloc,
        }

    @contextmanager
    def behind_proxy(self):
        """Odoo running with proxy_mode, as behind a trusted reverse proxy."""
        with patch.object(config, 'options', {**config.options, 'proxy_mode': True}):
            yield

    def frozen_throttle_clock(self):
        """The shared throttle counts in fixed one minute windows. Holding its
        clock keeps a burst inside one window, so counts are exact."""
        now = time.time()
        return patch.object(rate_limit, 'time', SimpleNamespace(time=lambda: now))
