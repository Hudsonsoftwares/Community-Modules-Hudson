# Face Kiosk Attendance

Browser-based face recognition clock-in / clock-out for Odoo 20
Community. Hybrid pipeline: face-api.js generates a 128-dim embedding
in the browser, the server runs cosine match against active templates
for the kiosk's company, and posts to `hr.attendance`.

## Privacy posture

* **Raw images never persist on the server.** The kiosk sends only
  the numeric embedding. Frames stay in the browser.
* **Templates are gated by consent.** No template exists without a
  granted `eh.hr.consent` of type `face`. Withdrawal cascades:
  every template tied to that consent is deactivated in the same
  transaction, audited, and excluded from future matches.
* **Audit-grade trail.** Every match attempt, match success, match
  failure, geofence pass / fail, and consent transition is written
  to `eh.hr.kiosk.event` (read-only for managers, append-only by
  design).

## Install

```
./odoo-bin -d <db> -i eh_hr_face_kiosk --without-demo=all
```

Depends on `eh_hr_attendance_base` (auto-installed) and `hr_attendance`.
Python dependency: `numpy` (already part of Odoo's runtime requirements).

### face-api.js bundle

The face-api.js library and model weights (about 6 MB) are not
bundled. The kiosk works out of the box anyway: when the files are
absent the page falls back to a pinned, immutable CDN build and the
server log records a warning. For production, vendor the files
locally with the supplied one-command script:

```sh
sh /path/to/addons/eh_hr_face_kiosk/tools/fetch_face_api.sh
./odoo-bin -d <db> -u eh_hr_face_kiosk
```

The script downloads the pinned 0.22.2 release into
`static/lib/face-api/`, verifies every file, and checks the manifests
parse as JSON. Air-gapped or no-third-party policy? Set the system
parameter `eh_hr_face_kiosk.disable_cdn_fallback` to `1`; the kiosk
then shows a setup-required panel instead of calling the CDN. Full
details, manual download commands, and troubleshooting live in
`static/lib/face-api/README.md`.

## Pairing a kiosk

1. Open People Operations > Kiosks > Sites and create a site.
2. With the site form open, click **Issue pairing PIN** (admin only).
3. On the device that will run the kiosk, browse to
   `/eh_hr/kiosk/<site_code>`.
4. Enter the PIN. The server issues an opaque device token that the
   browser stores in localStorage; the device is then registered.

## Enrolling an employee

1. Open the employee record. Under **Attendance and consent**,
   click **Enrol face**.
2. The wizard shows the company's default consent text. The employee
   reads it; the operator ticks the acknowledgement box.
3. Click **Start capture**. The widget captures five samples in
   varied lighting / angles, generates an embedding for each, and
   stores them in the form field.
4. Click **Save consent and enrol**. The wizard creates one
   `eh.hr.consent` (granted), one consent text snapshot, and five
   `eh.hr.face.template` rows.

Self-service enrolment via the kiosk itself is a Wave 2 follow-up.

## Architecture map

| Concern | Where |
|---|---|
| Embedding storage, multi-template | `eh.hr.face.template` |
| Template access: own only for the User role, metadata for the Auditor and Manager, the embedding for the Admin role only | `security/ir.access.csv` + field groups on `embedding` |
| Consent withdrawal cascade | `eh.hr.consent` override + retention cron |
| Employee fields, enrol/view buttons | `hr.employee` extension |
| Match endpoint, attendance toggle, geofence check | `controllers/face_match.py` |
| Public kiosk shell HTML | `controllers/kiosk_shell.py` + `kiosk_shell` QWeb template |
| Kiosk JS (vanilla) | `static/src/js/kiosk_shell.js`, `face_capture.js` |
| Backend enrolment OWL widget | `static/src/js/enrolment_widget.js` |
| Kiosk styles, dark mint aesthetic | `static/src/scss/kiosk.scss` |

## Performance notes

* Cosine match is a Python loop in this module. Acceptable for sites
  up to ~2,000 active templates per company. Past that, swap in a
  faiss-style vector index (a separate `eh_hr_face_kiosk_faiss` module
  is the right place for it; out of scope for Wave 1).
* The kiosk shell uses `localStorage` for the device token. Clear it
  via the device's browser settings to force re-pairing.

## Apps Store readiness checklist

Operator action, not committed:

* `static/description/banner.png` (1200x630)
* `static/description/icon.png` (140x140)
* `static/description/index.html` (English only, no external links)
* `static/lib/face-api/` populated per the README in that directory

Module display name "Face Kiosk Attendance" is 21 chars (under 25).

## Honest gaps (Wave 1)

* No active liveness (blink, head turn, smile prompt). Passive only:
  a low-res photo attack will pass the matcher. Wave 4 module
  `eh_hr_face_liveness` adds the active prompt step.
* No mobile / PWA. Wave 2 module `eh_hr_attendance_geofence` adds
  phone clock-in.
* No payroll export. Wave 3.
