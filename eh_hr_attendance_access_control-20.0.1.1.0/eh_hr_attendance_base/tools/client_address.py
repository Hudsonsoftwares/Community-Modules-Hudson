# -*- encoding: utf-8 -*-
"""Who is calling a public route: the one rule the attendance suite uses.

The kiosk, mobile, visitor, health, liveness and access routes are public.
They count a caller's requests to throttle it, and they record the caller's
address in the audit trail. Both use the address from here, and nothing else.

The address is the one Odoo's HTTP layer resolved. Straight to Odoo that is
the socket peer. Behind a reverse proxy it is the proxy, unless Odoo runs
with proxy_mode and the proxy sends X-Forwarded-For and X-Forwarded-Host, as
Odoo's deployment guide asks: Odoo then applies werkzeug's ProxyFix
(odoo/http/server.py and router.py) and takes the last X-Forwarded-For hop,
the one the trusted proxy appended.

X-Real-IP and the leading X-Forwarded-For entries are whatever the caller
chose to write, so they are never read. A throttle keyed on them is reset by
a new header on every request, and an audit trail keyed on them records
what the caller claims.

The cost of the rule: behind a reverse proxy without proxy_mode, or with a
proxy that does not send X-Forwarded-Host, every caller is the proxy's
address. They then share one throttle budget, and the audit trail records
the proxy.
"""
import ipaddress

from odoo.http import request


def client_ip():
    """The caller's address as Odoo's HTTP layer resolved it: what the audit
    trail records."""
    return request.httprequest.remote_addr or ''


def client_bucket(address=None):
    """The key a caller's requests are counted under: client_ip(), or the
    /64 it belongs to for IPv6, since one IPv6 host is typically handed a
    whole /64 and could otherwise pose as any number of callers. An IPv4
    caller seen on a dual stack socket (::ffff:a.b.c.d) is counted as its
    IPv4 address, not lumped in with every other IPv4 caller."""
    address = client_ip() if address is None else address
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address or 'anon'
    if ip.version == 6:
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network((int(ip) >> 64 << 64, 64)))
    return str(ip)
