# -*- encoding: utf-8 -*-
"""Guessing the kiosk pairing PIN, and who manages a paired terminal.

A kiosk trades a six digit PIN for a device token at POST /eh_hr/kiosk/pair.
The route is public and the site code is printed in the kiosk URL, so the
PIN is all that stands between an outsider and a terminal of their own: a
million values, live for five minutes.

Two things are held at once. Guessing is bounded: every client has an
attempt budget, and a PIN that takes more wrong guesses than one client can
send while it is live is withdrawn. And guessing cannot be turned against
the real kiosk: a client spends its own budget only, never the site's, so
from one address nobody holds a site at 429 or withdraws the PIN an admin
just issued. A client is the address Odoo's HTTP layer resolves, which a
header the client writes itself does not change.

A paired terminal is then configured by the Admin role, as its form says:
the Manager reads the registry but no longer renames, moves or revokes a
terminal over RPC.
"""
import json
import threading
from unittest.mock import patch
from urllib.parse import urlsplit

from odoo.tests import HttpCase, new_test_user, tagged
from odoo.tests.common import JsonRpcException
from odoo.tools import config, mute_logger

from odoo.addons.eh_hr_attendance_base.controllers import kiosk
from odoo.addons.eh_hr_attendance_base.controllers.kiosk import issue_pairing_pin


# The contract of the pair route: attempts a client gets per sliding minute
# (the mobile pair route's budget), how long a PIN lives, and the wrong PINs
# a live PIN survives. One client sends at most its budget in each of the
# minutes a PIN's life touches, 10 x 6, so no single client reaches the cap.
PAIR_BUDGET = 10
WINDOW_SECONDS = 60
PIN_LIFETIME = 300
MAX_FAILURES = 60

ACCESS_ERROR = 'odoo.exceptions.AccessError'


def _wrong(pin, n):
    """The n-th PIN that is not ``pin``."""
    return '%06d' % ((int(pin) + n) % 1000000)


class _ThreadedServer:
    """Serves a second pair request the way a threaded server may: the moment
    the request that looked up the PIN ``watched`` lets go of the route's lock,
    before that request goes on. It stands in for the route's lock and its PIN
    store, and ``competitor`` is the second request. The HTTP test server runs
    one request at a time, so without it no request ever runs in between."""

    def __init__(self, competitor):
        self._lock = threading.Lock()
        self.pins = _WatchedPins(self)
        self.watched = None
        self.competitor = competitor
        self._due = False

    def looked_up(self, pin):
        if pin == self.watched and self.competitor:
            self._due = True

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, *exc_info):
        self._lock.release()
        if self._due:
            self._due = False
            competitor, self.competitor = self.competitor, None
            competitor()
        return False


class _WatchedPins(dict):
    """The route's PIN store, telling the server when a PIN is looked up."""

    def __init__(self, server):
        super().__init__()
        self._server = server

    def get(self, pin, default=None):
        self._server.looked_up(pin)
        return super().get(pin, default)


@tagged('post_install', '-at_install')
class TestKioskPairGuard(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.site = cls.env['eh.hr.kiosk.site'].create({
            'name': 'Guard HQ',
            'code': 'guard-hq',
            'company_id': cls.company.id,
        })
        cls.other_site = cls.env['eh.hr.kiosk.site'].create({
            'name': 'Guard Depot',
            'code': 'guard-depot',
            'company_id': cls.company.id,
        })
        cls.admin = new_test_user(
            cls.env,
            login='eh_guard_admin',
            groups='base.group_user,eh_hr_attendance_base.group_eh_hr_admin',
            company_id=cls.company.id,
        )
        cls.Terminal = cls.env['eh.hr.kiosk.terminal'].with_context(active_test=False)

    def setUp(self):
        super().setUp()
        # The attempt counters live in this process, like the PINs they
        # protect. Start and end every test with none, so no other test's
        # requests count against these and none of these against theirs.
        self._forget_attempts()
        self.addCleanup(self._forget_attempts)

    def _forget_attempts(self):
        kiosk._PAIR_ATTEMPTS.clear()
        codes = (self.site.code, self.other_site.code)
        for pin, info in list(kiosk._PAIRING_PINS.items()):
            if info['site_code'] in codes:
                kiosk._PAIRING_PINS.pop(pin, None)

    def _post(self, site_code, pin, device_name, headers):
        """Without a ``pin`` nothing is posted. That is for a request the
        throttle refuses, before the route reads any body: a body the route
        never reads is still in the socket when the server closes it, and the
        client may then see a connection reset instead of the 429."""
        if pin is None:
            return self.url_open('/eh_hr/kiosk/pair', headers=headers, method='POST')
        return self.url_open(
            '/eh_hr/kiosk/pair',
            data=json.dumps({'site_code': site_code, 'pin': pin, 'device_name': device_name}),
            headers={'Content-Type': 'application/json', **headers},
        )

    def _pair(self, site_code, pin, client, device_name='Guard kiosk'):
        """Pair as the client at ``client``, reaching Odoo through a trusted
        reverse proxy. Odoo tells clients apart behind a proxy only in
        proxy_mode, from the X-Forwarded-For hop the proxy appends, and only
        when the proxy also sends X-Forwarded-Host."""
        headers = {
            'X-Forwarded-For': client,
            'X-Forwarded-Host': urlsplit(self.base_url()).netloc,
        }
        with patch.object(config, 'options', {**config.options, 'proxy_mode': True}):
            return self._post(site_code, pin, device_name, headers)

    def _pair_form(self, site_code, pin, client, device_name='Guard kiosk'):
        """As _pair, with the fields form encoded rather than in a JSON body.
        The route then reads them from its keyword arguments only, so a
        second request can be served inside this one with its own."""
        headers = {
            'X-Forwarded-For': client,
            'X-Forwarded-Host': urlsplit(self.base_url()).netloc,
        }
        with patch.object(config, 'options', {**config.options, 'proxy_mode': True}):
            return self.url_open('/eh_hr/kiosk/pair', data={
                'site_code': site_code, 'pin': pin, 'device_name': device_name}, headers=headers)

    def _pair_forging(self, site_code, pin, forged, device_name='Guard kiosk'):
        """Pair straight to Odoo (no proxy_mode), naming a made up address in
        every header a client could use to claim one."""
        return self._post(site_code, pin, device_name, {
            'X-Real-IP': forged,
            'X-Forwarded-For': forged,
            'X-Forwarded-Host': urlsplit(self.base_url()).netloc,
        })

    def _withdrawal_events(self, site):
        """The audit events the admin reads when a PIN of ``site`` stopped
        working, through the same call the event list makes."""
        self.authenticate(self.admin.login, self.admin.login)
        events = self.make_jsonrpc_request('/web/dataset/call_kw', {
            'model': 'eh.hr.kiosk.event',
            'method': 'search_read',
            'args': [[['event_type', '=', 'error'], ['notes', 'like', site.code]]],
            'kwargs': {'fields': ['notes', 'ip_address', 'company_id']},
        })
        self.logout()
        return events

    # ------------------------------------------------------------------
    # Throttle per client
    # ------------------------------------------------------------------
    @mute_logger('odoo.http')
    def test_a_client_runs_out_of_attempts(self):
        pin = issue_pairing_pin(self.site.code)
        before = self.Terminal.search([])
        # One client guesses, spreading its guesses over site codes so that
        # no count kept for a site is what stops it...
        for n in range(PAIR_BUDGET):
            response = self._pair('guard-guess-%s' % n, _wrong(pin, n + 1), '203.0.113.1')
            self.assertEqual(response.status_code, 403, n)
        # ...until its own budget is spent: the right PIN is then refused as
        # well, and is not used up by the refusal.
        response = self._pair(self.site.code, pin, '203.0.113.1')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json(), {'error': 'rate_limited'})
        self.assertEqual(self.Terminal.search([]), before)
        # The real kiosk, another client, is not held back by it.
        response = self._pair(self.site.code, pin, '203.0.113.2', 'Front desk')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.Terminal.search([('name', '=', 'Front desk')]).site_id, self.site)

    @mute_logger('odoo.http')
    def test_a_forged_address_header_is_not_a_new_client(self):
        """The route took the client from X-Real-IP or the first
        X-Forwarded-For entry, which any caller writes, so a guesser named a
        new address on every request and its budget never ran out. Odoo
        takes an address from X-Forwarded-For in proxy_mode only, and then
        the last hop, the one the trusted proxy appended."""
        pin = issue_pairing_pin(self.site.code)
        before = self.Terminal.search([])
        # Straight to Odoo, the client is the socket peer, whatever it says.
        # Past the budget a guess carries no body: the throttle refuses it
        # before any is read.
        statuses = [
            self._pair_forging('guard-guess-%s' % n, _wrong(pin, n + 1) if n < PAIR_BUDGET else None,
                               '203.0.113.%s' % n).status_code
            for n in range(PAIR_BUDGET + 1)
        ]
        self.assertEqual(statuses, [403] * PAIR_BUDGET + [429])
        # Behind the proxy, the leading hops are the client's own words.
        statuses = [
            self._pair('guard-guess-%s' % n, _wrong(pin, n + 1) if n < PAIR_BUDGET else None,
                       '198.51.100.%s, 192.0.2.40' % n).status_code
            for n in range(PAIR_BUDGET + 1)
        ]
        self.assertEqual(statuses, [403] * PAIR_BUDGET + [429])
        # One IPv6 host is handed a whole /64: it is one client.
        statuses = [
            self._pair('guard-guess-%s' % n, _wrong(pin, n + 1) if n < PAIR_BUDGET else None,
                       '2001:db8:40:1::%x' % (n + 1)).status_code
            for n in range(PAIR_BUDGET + 1)
        ]
        self.assertEqual(statuses, [403] * PAIR_BUDGET + [429])
        # IPv4 clients seen on a dual stack socket are not one IPv6 /64: a
        # client there spends its own budget only.
        statuses = [
            self._pair('guard-guess-%s' % n, _wrong(pin, n + 1) if n < PAIR_BUDGET else None,
                       '::ffff:192.0.2.42').status_code
            for n in range(PAIR_BUDGET + 1)
        ]
        self.assertEqual(statuses, [403] * PAIR_BUDGET + [429])
        self.assertEqual(self.Terminal.search([]), before)
        # The kiosk, a client of its own, pairs.
        response = self._pair(self.site.code, pin, '::ffff:192.0.2.41', 'Front desk')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.Terminal.search([('name', '=', 'Front desk')]).site_id, self.site)

    # ------------------------------------------------------------------
    # Guessing cannot be turned against the kiosk
    # ------------------------------------------------------------------
    @mute_logger('odoo.http')
    def test_other_clients_do_not_spend_the_sites_attempts(self):
        """Every attempt used to be charged to the site as well, so ten
        requests a minute naming the site, from anywhere, held the real
        kiosk at 429 even with the right PIN."""
        pin = issue_pairing_pin(self.site.code)
        other_pin = issue_pairing_pin(self.other_site.code)
        before = self.Terminal.search([])
        for n in range(PAIR_BUDGET):
            response = self._pair(self.site.code, _wrong(pin, n + 1), '198.51.100.%s' % n)
            self.assertEqual(response.status_code, 403, n)
        self.assertEqual(self.Terminal.search([]), before)
        response = self._pair(self.site.code, pin, '198.51.100.200', 'Front desk')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.Terminal.search([('name', '=', 'Front desk')]).site_id, self.site)
        # Another site is not held back either.
        response = self._pair(self.other_site.code, other_pin, '198.51.100.201', 'Depot kiosk')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.Terminal.search([('name', '=', 'Depot kiosk')]).site_id, self.other_site)

    @mute_logger('odoo.http')
    def test_one_address_cannot_keep_the_kiosk_out(self):
        """A single address guessing as fast as it is allowed, for the whole
        life of the PIN, neither holds the site at 429 nor gets the PIN
        withdrawn: the kiosk pairs with it at the last moment."""
        clock = [kiosk._now()]
        attacker = '203.0.113.66'
        with patch.object(kiosk, '_now', lambda: clock[0]):
            pin = issue_pairing_pin(self.site.code)
            issued = clock[0]
            guesses = 0
            # A burst every window, a second clear of the last one, from the
            # moment the PIN is issued until it lapses.
            for minute in range(PIN_LIFETIME // WINDOW_SECONDS):
                clock[0] = issued + minute * (WINDOW_SECONDS + 1) + 1
                for _attempt in range(PAIR_BUDGET):
                    guesses += 1
                    response = self._pair(self.site.code, _wrong(pin, guesses), attacker)
                    self.assertEqual(response.status_code, 403, guesses)
                # Beyond its budget the attacker waits, like anyone else. The
                # throttle refuses before reading a body, so none is sent.
                response = self._pair(self.site.code, None, attacker)
                self.assertEqual(response.status_code, 429, minute)
            self.assertEqual(guesses, PAIR_BUDGET * (PIN_LIFETIME // WINDOW_SECONDS))
            clock[0] = issued + PIN_LIFETIME - 1
            response = self._pair(self.site.code, pin, '192.0.2.10', 'Front desk')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.Terminal.search([('name', '=', 'Front desk')]).site_id, self.site)
        self.assertFalse(self._withdrawal_events(self.site))

    # ------------------------------------------------------------------
    # Withdrawing a PIN under attack
    # ------------------------------------------------------------------
    @mute_logger('odoo.http')
    def test_a_few_typos_still_pair(self):
        pin = issue_pairing_pin(self.site.code)
        for n in range(PAIR_BUDGET - 1):
            response = self._pair(self.site.code, _wrong(pin, n + 1), '192.0.2.10')
            self.assertEqual(response.status_code, 403, n)
        response = self._pair(self.site.code, pin, '192.0.2.10', 'Typist kiosk')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.Terminal.search([('name', '=', 'Typist kiosk')]).site_id, self.site)

    @mute_logger('odoo.http')
    def test_a_pin_is_withdrawn_after_more_guesses_than_one_client_sends(self):
        """Many addresses can together send what no single one may. A PIN
        takes MAX_FAILURES wrong PINs and still pairs; one more withdraws it,
        so a guesser has at most MAX_FAILURES + 1 tries at a million values,
        however many addresses it uses. The admin sees why the PIN stopped
        working."""
        pin = issue_pairing_pin(self.site.code)
        for n in range(MAX_FAILURES):
            client = '192.0.2.%s' % (20 + n // PAIR_BUDGET)
            response = self._pair(self.site.code, _wrong(pin, n + 1), client)
            self.assertEqual(response.status_code, 403, n)
        response = self._pair(self.site.code, pin, '192.0.2.98', 'Patient kiosk')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.Terminal.search([('name', '=', 'Patient kiosk')]).site_id, self.site)
        self.assertFalse(self._withdrawal_events(self.site))

        before = self.Terminal.search([])
        pin = issue_pairing_pin(self.site.code)
        for n in range(MAX_FAILURES + 1):
            client = '192.0.2.%s' % (40 + n // PAIR_BUDGET)
            response = self._pair(self.site.code, _wrong(pin, n + 1), client)
            self.assertEqual(response.status_code, 403, n)
        response = self._pair(self.site.code, pin, '192.0.2.99')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {'error': 'Invalid or expired pairing PIN'})
        self.assertEqual(self.Terminal.search([]), before)
        events = self._withdrawal_events(self.site)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['company_id'][0], self.company.id)
        # A fresh PIN starts a fresh count and pairs.
        pin = issue_pairing_pin(self.site.code)
        response = self._pair(self.site.code, pin, '192.0.2.99', 'Second try kiosk')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.Terminal.search([('name', '=', 'Second try kiosk')]).site_id, self.site)

    @mute_logger('odoo.http')
    def test_a_new_pin_outlives_the_one_under_attack(self):
        """Only the PIN that took the guesses is withdrawn. A PIN the admin
        issues while the site is being guessed counts from zero, so it is
        not lost with the old one."""
        def guess(n, pins):
            wrong = _wrong(first, n)
            while wrong in pins:
                wrong = _wrong(wrong, 1)
            client = '198.51.100.%s' % (10 + n // PAIR_BUDGET)
            self.assertEqual(self._pair(self.site.code, wrong, client).status_code, 403, n)

        first = issue_pairing_pin(self.site.code)
        early = MAX_FAILURES - 5
        for n in range(early):
            guess(n + 1, {first})
        second = issue_pairing_pin(self.site.code)
        # Guesses from here on count against both PINs, and push the first
        # one over its limit while the second has taken only a few.
        for n in range(early, MAX_FAILURES + 1):
            guess(n + 1, {first, second})
        self.assertEqual(self._pair(self.site.code, first, '198.51.100.99').status_code, 403)
        response = self._pair(self.site.code, second, '198.51.100.99', 'Replacement kiosk')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.Terminal.search([('name', '=', 'Replacement kiosk')]).site_id, self.site)
        self.assertEqual(len(self._withdrawal_events(self.site)), 1)

    @mute_logger('odoo.http')
    def test_a_guess_is_counted_before_another_request_is_checked(self):
        """A threaded server runs requests side by side. The route checked a
        PIN in one hold of its lock and counted the wrong guess in the next,
        so a request served in between was checked against a PIN the guess
        was about to withdraw: with MAX_FAILURES + 1 wrong PINs sent, the
        right one still paired a terminal, and more guesses than the limit
        were checked against the live PIN. The guess that crosses the limit
        is sent here, and a request with the right PIN is served the moment
        that guess lets go of the lock."""
        served = []

        def pair_with_the_right_pin():
            response = kiosk.EhHrKioskController().pair(
                site_code=self.site.code, pin=pin, device_name='Front desk')
            served.append(response.status_code)

        server = _ThreadedServer(pair_with_the_right_pin)
        with patch.object(kiosk, '_PAIR_LOCK', server), patch.object(kiosk, '_PAIRING_PINS', server.pins):
            pin = issue_pairing_pin(self.site.code)
            for n in range(MAX_FAILURES):
                client = '192.0.2.%s' % (60 + n // PAIR_BUDGET)
                response = self._pair(self.site.code, _wrong(pin, n + 1), client)
                self.assertEqual(response.status_code, 403, n)
            server.watched = _wrong(pin, MAX_FAILURES + 1)
            response = self._pair_form(self.site.code, server.watched, '192.0.2.90')
            self.assertEqual(response.status_code, 403)
            # The request served in between found the PIN already withdrawn.
            self.assertEqual(served, [403])
            self.assertFalse(self.Terminal.search([('name', '=', 'Front desk')]))
            self.assertEqual(len(self._withdrawal_events(self.site)), 1)
            # And so does any later one.
            self.assertEqual(self._pair(self.site.code, pin, '192.0.2.91').status_code, 403)

    @mute_logger('odoo.http')
    def test_a_live_pin_of_another_site_looks_like_any_wrong_pin(self):
        """A guess that hits another site's PIN is charged to the site it was
        sent for. Told apart from an unknown PIN, it would tell the guesser
        that a live PIN was found, at no cost to the budget of its own site."""
        other_pin = issue_pairing_pin(self.other_site.code)
        unknown = self._pair(self.site.code, _wrong(other_pin, 1), '192.0.2.50')
        crossed = self._pair(self.site.code, other_pin, '192.0.2.50')
        self.assertEqual(crossed.status_code, unknown.status_code)
        self.assertEqual(crossed.json(), unknown.json())
        # The depot's kiosk still pairs with it.
        response = self._pair(self.other_site.code, other_pin, '192.0.2.51', 'Depot kiosk')
        self.assertEqual(response.status_code, 200)


@tagged('post_install', '-at_install')
class TestTerminalAdministration(HttpCase):
    """Rename, move and revoke are Admin configuration: the Admin group
    comment lists revoke, and the form shows Revoke and Rotate to the Admin
    only. The Manager keeps reading the registry."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.manager, cls.admin = (
            new_test_user(
                cls.env,
                login='eh_terminal_%s' % role,
                groups='base.group_user,eh_hr_attendance_base.group_eh_hr_%s' % role,
                company_id=cls.company.id,
            )
            for role in ('manager', 'admin')
        )
        cls.site = cls.env['eh.hr.kiosk.site'].create({
            'name': 'Terminal HQ', 'code': 'terminal-hq', 'company_id': cls.company.id})
        cls.other_site = cls.env['eh.hr.kiosk.site'].create({
            'name': 'Terminal Depot', 'code': 'terminal-depot', 'company_id': cls.company.id})
        cls.device = cls.env['eh.hr.kiosk.terminal'].create({
            'name': 'Terminal kiosk', 'site_id': cls.site.id})

    def _login(self, user):
        self.authenticate(user.login, user.login)

    def _call_kw(self, model, method, args, kwargs=None):
        return self.make_jsonrpc_request('/web/dataset/call_kw', {
            'model': model, 'method': method, 'args': args, 'kwargs': kwargs or {},
        })

    def _call_button(self, model, method, ids):
        return self.make_jsonrpc_request('/web/dataset/call_button', {
            'model': model, 'method': method, 'args': [ids], 'kwargs': {},
        })

    def _assert_refused(self, call, *args, msg=None):
        with self.assertRaises(JsonRpcException, msg=msg) as caught:
            call(*args)
        self.assertEqual(caught.exception.args[0], ACCESS_ERROR, msg)

    def _heartbeat(self, token):
        return self.url_open(
            '/eh_hr/kiosk/heartbeat',
            data='{}',
            headers={'Content-Type': 'application/json', 'X-EH-Kiosk-Token': token},
        )

    @mute_logger('odoo.http')
    def test_only_an_admin_renames_moves_or_revokes_a_terminal(self):
        token = self.device.device_token
        self._login(self.manager)
        ids = self.device.ids
        for vals in ({'name': 'Renamed by the manager'},
                     {'site_id': self.other_site.id},
                     {'active': False}):
            self._assert_refused(self._call_kw, 'eh.hr.kiosk.terminal', 'write', [ids, vals], msg=vals)
        self._assert_refused(self._call_button, 'eh.hr.kiosk.terminal', 'action_revoke', ids)
        self.device.invalidate_recordset()
        self.assertEqual(
            (self.device.name, self.device.site_id, self.device.active),
            ('Terminal kiosk', self.site, True))
        self.assertEqual(self._heartbeat(token).status_code, 200)

        # The manager still reads the registry and opens the terminal form.
        rows = self._call_kw('eh.hr.kiosk.terminal', 'search_read', [[['id', '=', self.device.id]]], {
            'fields': ['name', 'site_id', 'last_seen', 'active']})
        self.assertEqual(rows[0]['name'], 'Terminal kiosk')
        views = self._call_kw('eh.hr.kiosk.terminal', 'get_views', [], {
            'views': [[False, 'list'], [False, 'form']]})['views']
        self.assertIn('form', views)
        self._call_kw('eh.hr.kiosk.terminal', 'web_read', [ids], {
            'specification': {'name': {}, 'site_id': {'fields': {'display_name': {}}},
                              'registered_on': {}, 'last_seen': {}, 'last_ip': {},
                              'user_agent': {}, 'notes': {}, 'active': {}}})

        # The administrator renames it and revokes it, and the kiosk is shut
        # out.
        self._login(self.admin)
        self._call_kw('eh.hr.kiosk.terminal', 'write', [ids, {'name': 'Renamed by the admin'}])
        self._call_button('eh.hr.kiosk.terminal', 'action_revoke', ids)
        self.device.invalidate_recordset()
        self.assertEqual(self.device.name, 'Renamed by the admin')
        self.assertFalse(self.device.active)
        self.assertEqual(self._heartbeat(token).status_code, 401)
