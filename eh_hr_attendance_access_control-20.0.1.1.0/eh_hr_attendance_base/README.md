# Attendance Suite Base

Foundation module for the ERP Heritage attendance and people-operations
modules on Odoo 20 Community. Auto-installs as a dependency of any
`eh_hr_*` module so it does not need to be installed manually.

This module has no end-user UI for capture or matching by itself. It
provides the data model, security, audit trail, retention lifecycle,
and kiosk pairing endpoints that every capture-modality module
(face, fingerprint, badge, mobile, etc.) builds on top of.

## What it provides

| Concern | Where |
|---|---|
| Biometric and location consent lifecycle | `eh.hr.consent` model + retention cron |
| Kiosk physical site, optional geofence, multi-company scoped | `eh.hr.kiosk.site` |
| Registered kiosk device with rotating opaque token | `eh.hr.kiosk.device` |
| Append-only kiosk audit trail with retention | `eh.hr.kiosk.event` |
| Attendance exceptions: late, no-show, low confidence, geofence violation | `eh.hr.attendance.exception` |
| Employee fields: consent state, fallback PIN, default site, enrolled flag | `hr.employee` extension |
| Company settings: validity, retention, threshold, idle reset | `res.company` + `res.config.settings` |
| Privilege groups: User, Manager, Admin, Auditor (read-only). User and Auditor imply no HR role; Manager and Admin imply HR Administrator | `security/eh_hr_security.xml` |
| Per-company record rules, employee-scoped consent visibility | `security/ir.access.csv` |
| Pairing endpoint, heartbeat, whoami | `controllers/kiosk.py` |

## What does NOT live here

The base module is deliberately modality-agnostic. The following are
provided by other modules in the suite:

* **Face capture and match.** `eh_hr_face_kiosk` (Wave 1).
* **Job / cost code punch after match.** `eh_hr_attendance_jobcost` (Wave 1).
* **Dashboards, exception detection cron, audit PDF.** `eh_hr_attendance_reports` (Wave 1).
* **PWA mobile and geofence enforcement at clock-in.** `eh_hr_attendance_geofence` (Wave 2).
* **Rosters and shift comparison.** `eh_hr_attendance_roster` (Wave 2).
* **Visitor sign-in.** `eh_hr_visitor` (Wave 2).
* **AU Fair Work / Modern Award OT engine.** `eh_hr_attendance_award_au` (Wave 3).
* **Payroll exports.** `eh_hr_attendance_payroll_export` (Wave 3).
* **Vendor-neutral CSV migration importer.** `eh_hr_attendance_migrate` (Wave 2).
* **Health declaration, access control, active liveness.** Wave 4.

## Install

```
./odoo-bin -d <db> -i eh_hr_attendance_base --without-demo=all
```

No external Python dependencies beyond what `hr` and `hr_attendance`
already require. The kiosk site timezone selection reuses the standard
Odoo timezone list, which is built on the Python standard library.

## Running behind a reverse proxy

The public routes of the suite (kiosk pairing, heartbeat, face match,
mobile pairing and clock, visitor sign in, health declaration, liveness
log, door trigger) limit how often each caller may call them, and record
the caller's address in the audit trail. They take that address from
Odoo, and never from a header the caller sends, such as `X-Real-IP` or the
first `X-Forwarded-For` entry, which anyone can fill in. The rule lives in
one place, `tools/client_address.py`, and every one of those routes uses
it.

Straight to Odoo, the address is the device's own. Behind nginx, Apache,
a load balancer or any other reverse proxy, Odoo sees the device's
address only when both of these hold:

* Odoo runs with `proxy_mode = True` (or `--proxy-mode`).
* The proxy sends `X-Forwarded-For` and `X-Forwarded-Host`, as Odoo's
  deployment guide shows.

Without them, every kiosk, phone and caller looks like the proxy. They
then share one allowance, so one busy or hostile caller can make the
others wait (a 429 answer), and the audit trail records the proxy's
address for everyone. Up to this release the routes read `X-Real-IP`
from any caller, so a proxy set up without `proxy_mode` used to work by
accident: after the upgrade, turn `proxy_mode` on.

An IPv6 caller is counted for its /64, since one device is usually given
a whole /64.

## Apps Store readiness checklist

Before publishing, the following non-code assets are maintained by the
release operator:

* `static/description/banner.png` (1200x630 recommended), referenced
  by the manifest's `images` key.
* `static/description/icon.png` (140x140), referenced by the menu
  `web_icon` and used as the apps store thumbnail.
* `static/description/index.html`, the apps store listing page,
  English-only, no external links.

The module name length is within the 25-character limit ("Attendance
Suite Base" = 22 chars).

## Engineering principles

* **Privacy by design.** Raw biometric images never persist on the
  server. Only embeddings live in the database (introduced by the
  capture-modality module), tied to a granted consent record. Consent
  withdrawal cascades to embedding deletion at the next kiosk match
  attempt.
* **Multi-company aware throughout.** Every model is company-scoped
  and guarded by record rules.
* **Defensible audit.** Every kiosk event is logged with a server
  timestamp the customer cannot edit; managers can read, never write.
  The `eh.hr.kiosk.event` model is intentionally write-blocked at
  the ACL layer for everyone except the daily retention cron.
* **No silent fallbacks.** Missing consent, missing site, missing
  device token each surface explicit messages.

## Roles

* **EH Attendance User.** Own attendance (through the standard Self
  Attendance Edit role, own rows only), own consent records, own
  attendance exceptions and face templates, and the kiosk site list. It
  does not imply HR Officer, so other employees are seen through their
  public profile only.
* **EH Attendance Auditor (read-only).** Read on the consent records,
  kiosk sites and terminals, the kiosk audit log and the attendance
  exceptions. It implies only the internal user role and cannot change
  any employee. Terminals are read without their device token.
* **EH Attendance Manager and Admin.** Imply HR Administrator on purpose.
  Only the Admin role issues kiosk pairing PINs and reads or rotates a
  device token (and, with the face kiosk, reads a face embedding).

These rules hold on every entry point, not only on the screens. The
device token carries the Admin group on the field, the pairing PIN
action checks for the Admin role in the method, and the audit log and
exception APIs below, which create as superuser, are not callable over
RPC.

Up to 20.0.1.0.0 the User and Auditor roles implied HR Officer, which is
create, write and delete on every employee. The 20.0.1.1.0 upgrade gives
HR Officer explicitly to every user who held it only through those two
roles, so nobody loses access overnight, and logs their logins at INFO
(`EH Attendance User and EH Attendance Auditor no longer imply HR
Officer`) for an administrator to review and revoke. Assignments made
after the upgrade are least privilege.

## Public APIs for downstream modules

* `eh.hr.kiosk.event.log(event_type, **kwargs)`: single entry point
  for any module to write to the audit trail. `event_type` is the
  only required argument. Server side only (`@api.private`): call it
  in process, as the kiosk routes do.
* `eh.hr.attendance.exception.raise_exception(employee, exception_type, ...)`:
  API for raising an exception. Logs a kiosk event in the same call.
  Server side only (`@api.private`), like `log`.
* `eh_hr_attendance_base.controllers.kiosk.issue_pairing_pin(site_code)`:
  generate a 5-minute one-shot pairing PIN bound to a site. The site's
  **Issue pairing PIN** button calls it for the Admin role only.
* `eh_hr_attendance_base.tools.client_address.client_ip()` and
  `client_bucket()`: the caller's address for the audit trail, and the key
  to count its requests under (its /64 for IPv6), for any public route. See
  "Running behind a reverse proxy".

## Tests

Tests are added in a separate sweep across all Wave 1 modules so
fixtures and helpers can be shared. The `tests/` directory exists for
that sweep.

## Roadmap

`eh_hr_attendance_base` is the foundation for a 13-module suite that
replaces biometric T&A SaaS for Odoo 20 Community customers. Wave 1
ships the foundation, face kiosk, job costing, and reports. Subsequent
waves add geofence, rosters, visitor management, AU award engine, and
payroll exports. The base module's data model is designed so new
capture modalities (fingerprint, badge, mobile) can plug in without
schema migration.
