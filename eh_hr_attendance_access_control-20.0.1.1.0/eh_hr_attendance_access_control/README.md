# Door Access Control

Triggers a door or zone unlock when an authorised employee's face
match succeeds at the kiosk. HTTP-webhook reader protocol for
vendor neutrality, per-employee zone permissions, full audit trail.

## Install

```
./odoo-bin -d <db> -i eh_hr_attendance_access_control
```

Depends on `eh_hr_attendance_base` and `eh_hr_face_kiosk`. Python
external dependency: `requests` (standard in any Odoo deployment).

## Architecture

| Model | Purpose |
|---|---|
| `eh.hr.access.zone` | A controlled space ("Front door", "Server room"). One or more kiosk sites grant access here. |
| `eh.hr.access.reader` | The bridge endpoint that physically unlocks. Holds the webhook URL, bearer token, auto-relock seconds. |
| `eh.hr.access.permission` | Employee + zone + optional valid-from / valid-to dates. |
| `eh.hr.access.event` | Append-only audit row per unlock attempt. |

## Reader protocol

This module ships exactly one protocol: **HTTP webhook**. The
module POSTs the following JSON to the reader's configured URL:

```json
{
    "action": "unlock",
    "employee_id": 42,
    "employee_name": "Alice Test",
    "zone_id": 7,
    "zone_code": "front-door",
    "reason": "kiosk_face_match",
    "auto_relock_seconds": 5
}
```

The reader returns:
* `2xx` for success, body is logged.
* `4xx` for denied at the reader (door already locked open, scheduled curfew, etc.), body is logged.
* `5xx` or network failure for an error.

For non-HTTP hardware (Wiegand, MQTT, relay over TCP, proprietary
boards) install a small bridge service in front of the hardware
that listens on HTTP and translates. A bridge is typically 30 to
80 lines of Python or Node.js. This keeps the Odoo side
vendor-neutral.

## Configuration flow

1. **Create a zone** under People Operations &gt; Access control &gt; Zones.
   Tick which kiosk sites grant access here.
2. **Add a reader** to the zone with the bridge service's URL and
   (optionally) a bearer token. Click **Test unlock** to verify
   the bridge responds.
3. **Grant permissions** under People Operations &gt; Access control
   &gt; Permissions. One row per employee + zone, optional
   valid-from / valid-to.
4. The kiosk JS hook fires the unlock automatically after every
   successful face match at a site that maps to a zone.

## Roles

| Role | Zones | Readers | Permissions | Events |
|---|---|---|---|---|
| EH Attendance User | Read | None | Reads only their own | None |
| EH Attendance Manager | Create, read, write | Read | Create, read, write | Read |
| EH Attendance Admin | Full access | Full access | Full access | Read, delete |
| EH Attendance Auditor | Read | Read (no bearer token) | Read | Read |

The door list on the employee form is shown to managers and auditors
only: an HR Officer who is only an EH Attendance User there would
otherwise see a colleague's doors as an empty list. The kiosk unlock
checks permissions as superuser once the device token is known, so
it does not depend on what staff can read. Every rule also keeps each
company's rows apart.

## Audit trail

Every attempt lands in `eh.hr.access.event` with one of these
outcomes:

| Outcome | Cause |
|---|---|
| `allowed` | Reader returned 2xx |
| `denied` | Employee has no active permission for the zone |
| `reader_denied` | Reader returned 4xx |
| `reader_error` | Reader returned 5xx or did not respond |
| `no_reader` | Zone has no active reader configured |
| `no_zone` | Site does not map to any active zone |

Daily retention cron prunes events past the company horizon (default 365 days).

## Apps Store readiness checklist

Operator action: `static/description/banner.png`, `icon.png`,
`index.html`. Module display name "Door Access Control" is 20 chars.

## Honest gaps and security notes

* **The kiosk JS fires the unlock fire-and-forget.** If the bridge
  is unreachable the user still sees the kiosk success screen.
  This is intentional: the door is a side effect of the match,
  not a gate on it. Audit through the Access events list.
* **Bearer token only authenticates Odoo-to-bridge.** The bridge
  is responsible for keeping its own connection to the door
  hardware safe. We assume the bridge runs on a trusted local
  network segment with the door controller.
* **No anti-tailgate detection.** The unlock fires once; whoever
  walks through is the system's problem to track via the camera
  attached to a bypass-detection product, not by us.
* **No multi-zone-per-site ranking.** First active zone wins. If
  a site spans multiple zones with different permissions, raise
  separate sites or use multiple zones with the same reader URL.
* **No time-of-day windows on permissions.** Date-range only.
  Time-of-day restrictions belong on the bridge service or in a
  follow-up module.
* **No audit on reader configuration changes for non-admins.**
  The `bearer_token` field is admin-only and the reader form
  inherits the standard chatter, so changes are tracked.
