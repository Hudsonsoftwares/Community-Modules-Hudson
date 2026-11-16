# Hudson Activity Agent

Lightweight desktop agent (Windows + macOS) that records **active time, idle time,
locked time and the applications/windows used**, and uploads them to Odoo
(`hudson_activity_monitor` module).

This folder has no `__manifest__.py`, so Odoo ignores it.

## How it works

```
every 5 s:  idle seconds + foreground app/title  ──▶  Tracker merges identical samples into spans
span closes (app switch / idle / lock / midnight) ──▶  SQLite queue (offline-safe)
every 2 min: queued spans + the live span         ──▶  POST /api/activity/ingest  (batch of ≤500)
```

* **Idle** = no keyboard/mouse input for `idle_threshold` seconds (default 300). Idle is
  back-dated to the last input, so the 5 minutes of waiting are not counted as active.
* **Locked** = screen locked / lock screen / screensaver.
* **Sleep/hibernate** is detected by the gap between samples; the span ends at the last sample.
* Spans are **split at local midnight**, so each span belongs to exactly one day.
* The open span is checkpointed to disk every 30 s, so a crash or power cut loses ≤30 s.
* The server controls the settings (intervals, titles on/off, private apps, pause) via the
  `config` object in every response.

Measured on Windows 11 (built `.exe`): **~54 MB RAM, <1% CPU**, 20 MB file.

## Layout

| File | Purpose |
|---|---|
| `agent/platforms/windows.py` | idle time, foreground app, friendly app name, lock detection, autostart (ctypes only) |
| `agent/platforms/macos.py` | same for macOS (PyObjC); LaunchAgent autostart |
| `agent/tracker.py` | samples → spans |
| `agent/store.py` | SQLite offline queue + live-span checkpoint |
| `agent/api.py`, `agent/uploader.py` | HTTP client, batched uploads with back-off |
| `agent/tray.py` | tray/menu-bar icon (green = tracking, grey = paused, orange = offline, red = not paired) |
| `agent/pairing.py` | first-run pairing window |
| `tools/mock_server.py` | stand-in for the Odoo endpoints, with a simple web view |

## Run from source

```bash
pip install -r requirements.txt
python run_agent.py --dry-run -v              # print spans to the console, no server needed
python -m unittest discover -s tests          # unit tests
```

Test against the mock server:

```bash
python tools/mock_server.py --fast            # http://localhost:8099, pairing code 123456
python run_agent.py --pair-url http://localhost:8099 --pair-code 123456
# open http://localhost:8099/ to see what was received
```

Command-line options: `--pair-url/--pair-code` (silent pairing for mass deployment), `--no-tray`,
`--unpair`, `--remove-autostart`, `--data-dir`, `--verbose`.

Data folder: `%LOCALAPPDATA%\HudsonActivity` (Windows), `~/Library/Application Support/HudsonActivity` (macOS).

## Build

* **Windows:** `powershell -ExecutionPolicy Bypass -File build_windows.ps1` → `dist\HudsonActivity.exe`
* **macOS** (must be built on a Mac): `./build_macos.sh` → `dist/HudsonActivity.app` (ad-hoc signed, menu-bar only)

When a frozen build pairs for the first time it registers itself to start at login
(`HKCU\...\Run` on Windows, `~/Library/LaunchAgents/com.hudsonsoftwares.activity.plist` on macOS).

### Installing unsigned builds
* **Windows:** "Windows protected your PC" → *More info* → *Run anyway* (once).
* **macOS:** open once, then *System Settings → Privacy & Security → Open Anyway*. For window
  titles also allow *Screen Recording* for HudsonActivity.

## API contract (implemented by `hudson_activity_monitor`)

Server URL format: `https://erp.example.com?db=DATABASE`. The `?db=` part is needed when the
Odoo server hosts several databases; the agent sends it as the `X-Odoo-Database` header on
every request (Odoo 20 selects the database from that header). Odoo shows the exact URL
in the pairing popup.

All bodies are JSON. Timestamps are UTC ISO-8601 (`2026-11-08T05:17:03Z`).

### `POST /api/activity/pair` (no auth)
Request:
```json
{"code": "123456", "device_uid": "uuid", "hostname": "NANDU", "os": "Windows-11-...",
 "os_user": "nandu", "agent_version": "0.1.0"}
```
Response `200`: `{"token": "<device token>", "employee": "Jane Doe", "database": "DB", "config": {...settings}}`
Error `400`: `{"error": "Invalid or expired pairing code"}`

### `POST /api/activity/ingest` (header `Authorization: Bearer <token>`)
Request:
```json
{"device_uid": "uuid", "agent_version": "0.1.0",
 "spans": [{"uid": "uuid", "start": "...Z", "end": "...Z", "duration": 34,
            "state": "active|idle|locked", "app": "Google Chrome", "process": "chrome.exe",
            "title": "Inbox - Gmail", "open": false}]}
```
* `spans` may be empty (a heartbeat: update "last seen", return settings).
* **Upsert by `uid`**: the same span is re-sent while it is open (`open: true`, growing `end`)
  and once more when it closes. Never let an `open: true` update overwrite a closed span.
  Re-sends after network errors are therefore harmless.

Response `200`: `{"accepted": 3, "config": {...settings}}`
`401/403`: the token was revoked, so the agent stops tracking and shows "Not paired".

### Settings (`config`), all optional
| Key | Default | Notes |
|---|---|---|
| `tracking_enabled` | `true` | `false` pauses tracking (e.g. outside work hours / not checked in) |
| `sample_interval` | `5` | seconds, 1–60 |
| `idle_threshold` | `300` | seconds, 30–7200 |
| `upload_interval` | `120` | seconds, 15–3600 |
| `capture_titles` | `true` | send window titles |
| `private_apps` | `[]` | process names / bundle ids whose titles are never sent |
| `max_title_length` | `255` | |
| `allow_quit` | `true` | show *Quit* in the tray menu |
| `dashboard_url` | `""` | target of *Open my activity* |
