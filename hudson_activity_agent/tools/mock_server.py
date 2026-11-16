"""Tiny stand-in for the Odoo endpoints, for testing the agent before the module exists.

    python tools/mock_server.py --port 8099 --code 123456
    python run_agent.py --pair-url http://localhost:8099 --pair-code 123456

Open http://localhost:8099/ to see what the agent sent.
"""
import argparse
import html
import json
import secrets
import threading
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {"tokens": {}, "spans": {}}
LOCK = threading.Lock()
ARGS = None


class Handler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_POST(self):
        if self.path == "/api/activity/pair":
            data = self._body()
            if data.get("code") != ARGS.code:
                return self._json(400, {"error": "Invalid or expired pairing code"})
            token = secrets.token_urlsafe(32)
            with LOCK:
                STATE["tokens"][token] = data
            print(f"[pair] {data.get('hostname')} ({data.get('os')}) user={data.get('os_user')}")
            config = {"dashboard_url": f"http://localhost:{ARGS.port}/"}
            if ARGS.fast:
                config.update(upload_interval=15, sample_interval=2)
            return self._json(200, {"token": token, "employee": "Demo Employee", "config": config})

        if self.path == "/api/activity/ingest":
            token = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
            if token not in STATE["tokens"]:
                return self._json(401, {"error": "Unknown device token"})
            spans = self._body().get("spans", [])
            with LOCK:
                for s in spans:
                    existing = STATE["spans"].get(s["uid"])
                    if existing and not existing["open"] and s["open"]:
                        continue  # never downgrade a closed span to open
                    STATE["spans"][s["uid"]] = s
            closed = sum(1 for s in spans if not s["open"])
            print(f"[ingest] {len(spans)} spans ({closed} closed, {len(spans) - closed} live)")
            return self._json(200, {"accepted": len(spans), "config": {}})

        self._json(404, {"error": "not found"})

    def do_GET(self):
        if self.path != "/":
            return self._json(404, {"error": "not found"})
        with LOCK:
            spans = sorted(STATE["spans"].values(), key=lambda s: s["start"])
        totals = defaultdict(int)
        for s in spans:
            totals[s["app"] or s["state"]] += s["duration"]
        rows = "".join(
            f"<tr><td>{html.escape(k)}</td><td>{v // 60}m {v % 60}s</td></tr>"
            for k, v in sorted(totals.items(), key=lambda kv: -kv[1]))
        recent = "".join(
            f"<tr><td>{s['start'][11:19]}</td><td>{s['end'][11:19]}</td><td>{s['duration']}s</td>"
            f"<td>{s['state']}{' (live)' if s['open'] else ''}</td><td>{html.escape(s['app'] or '')}</td>"
            f"<td>{html.escape(s['title'] or '')}</td></tr>"
            for s in reversed(spans[-50:]))
        page = f"""<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="10">
<title>Activity mock</title><style>body{{font-family:sans-serif;margin:24px}}
table{{border-collapse:collapse;margin-bottom:24px}}td,th{{border:1px solid #ccc;padding:4px 8px;text-align:left}}</style>
<h2>Time per app / state</h2><table><tr><th>App</th><th>Time</th></tr>{rows}</table>
<h2>Last 50 spans (UTC)</h2><table><tr><th>Start</th><th>End</th><th>Dur</th><th>State</th><th>App</th><th>Title</th></tr>{recent}</table>"""
        body = page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def main():
    global ARGS
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1",
                   help="Use 0.0.0.0 to accept agents from other devices on the network")
    p.add_argument("--port", type=int, default=8099)
    p.add_argument("--code", default="123456")
    p.add_argument("--fast", action="store_true", help="Push short intervals to the agent (testing)")
    ARGS = p.parse_args()
    print(f"Mock server on http://{ARGS.host}:{ARGS.port}  (pairing code {ARGS.code})")
    ThreadingHTTPServer((ARGS.host, ARGS.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
