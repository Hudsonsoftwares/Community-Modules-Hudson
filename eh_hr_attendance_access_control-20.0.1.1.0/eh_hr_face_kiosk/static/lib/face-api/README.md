# face-api.js bundle: setup, fallback, and troubleshooting

The kiosk module deliberately does not vendor face-api.js or its model
weights into the repository or the Apps Store zip. Reasons:

1. The model files weigh in around six megabytes. Operators may want
   to pin a specific release rather than inherit the one that happened
   to be current when the module was published.
2. face-api.js is MIT-licensed but is no longer actively maintained.
   Operators may swap in a maintained fork without us forcing a
   specific provenance.

**The kiosk still works without any setup.** When these files are
absent, the kiosk page and the enrolment wizard automatically fall
back to a pinned, immutable CDN build (jsDelivr serving the upstream
GitHub tag 0.22.2). Vendoring the files locally is recommended for
production: it removes the third-party request, works offline and
behind strict firewalls, and gives you control over the exact bytes.

## What you need here

```
static/lib/face-api/
  face-api.min.js                # the library
  models/
    tiny_face_detector_model-shard1                # ~190 KB
    tiny_face_detector_model-weights_manifest.json
    face_landmark_68_model-shard1                  # ~350 KB
    face_landmark_68_model-weights_manifest.json
    face_recognition_model-shard1                  # ~4.2 MB
    face_recognition_model-shard2                  # ~2.2 MB
    face_recognition_model-weights_manifest.json
```

The kiosk's JavaScript loads `tiny_face_detector`, `face_landmark_68`,
and `face_recognition`. Other models (expressions, age/gender) are not
required. Keep the filenames exactly as listed: the
`*-weights_manifest.json` files reference the shard names.

## Option A: the supplied fetch script (recommended)

Run once on the Odoo server, from anywhere:

```sh
sh /path/to/addons/eh_hr_face_kiosk/tools/fetch_face_api.sh
```

The script downloads the pinned 0.22.2 release into this directory,
verifies every file is non-empty, and checks that the three manifests
parse as JSON (a saved 404 page is the classic silent failure).
`--force` redownloads; `--source github` switches the download host
from jsDelivr to raw.githubusercontent.com.

Then restart Odoo with the module updated and hard-refresh the kiosk:

```sh
./odoo-bin -d <db> -u eh_hr_face_kiosk
```

## Option B: manual download

```sh
cd /path/to/addons/eh_hr_face_kiosk/static/lib/face-api
curl -fsSLO https://raw.githubusercontent.com/justadudewhohacks/face-api.js/0.22.2/dist/face-api.min.js
mkdir -p models && cd models
BASE=https://raw.githubusercontent.com/justadudewhohacks/face-api.js/0.22.2/weights
for f in tiny_face_detector_model-weights_manifest.json tiny_face_detector_model-shard1 \
         face_landmark_68_model-weights_manifest.json face_landmark_68_model-shard1 \
         face_recognition_model-weights_manifest.json face_recognition_model-shard1 \
         face_recognition_model-shard2; do curl -fsSLO "$BASE/$f"; done
```

For air-gapped servers: run the same commands on a connected machine,
verify, and copy the directory across.

## How the fallback works

At request time the kiosk controller checks whether all eight files
above exist and are non-empty.

* **All present:** the page serves the library and models from this
  Odoo instance. No third-party request is ever made.
* **Any missing:** the page points the browser at the pinned CDN build
  instead, logs a warning in the Odoo server log naming the fetch
  script, and the kiosk works normally. The browser-side loader also
  retries via the CDN if a local file turns out to be corrupt or
  blocked mid-session.

Only the library and model weights are ever fetched from the CDN.
Face embeddings, frames, and any user data never leave the device
except to your own Odoo server.

### Disabling the CDN fallback

For no-third-party or air-gapped policies, set the system parameter
`eh_hr_face_kiosk.disable_cdn_fallback` to `1` (Settings > Technical >
System Parameters). With the parameter set and the files missing, the
kiosk page renders a "Kiosk setup required" panel naming this README
and the fetch script instead of calling out to the CDN.

The backend enrolment wizard always tries the local files first and
uses the CDN only when they are missing; it runs for HR admins inside
the backend, not on public kiosk devices.

## Reverse proxy note

The browser sees this URL prefix: `/eh_hr_face_kiosk/static/lib/face-api/`.
If you serve Odoo behind a reverse proxy that aggressively caches
static assets, set a long max-age; the model files are immutable for
the bundle's lifetime.

## Sanity check

After setup, visit `/eh_hr/kiosk/<your-site-code>` in a browser. The
welcome screen should load and the camera should activate within a
second.

## Troubleshooting

* **"failed to fetch (404)" on a model URL.** The files are missing
  from this directory (or only partially copied). Run Option A above.
  Versions of this module before 1.1.0 had no CDN fallback, so a 404
  here stopped the kiosk outright; from 1.1.0 the kiosk self-heals via
  the CDN and the 404 only means the local vendoring step is pending.
* **"Camera or model load failed" stays on screen.** Usually one of
  the model shard files is missing or served as `text/html` (often a
  404 wrapped in your reverse proxy's error page). The fetch script's
  validation step catches the saved-error-page case.
* **"Kiosk setup required" panel.** The files are missing AND the
  `eh_hr_face_kiosk.disable_cdn_fallback` parameter is set. Vendor
  the files (Option A or B), then reload.
* **Strict Content-Security-Policy devices.** If your kiosk devices
  enforce a CSP that blocks `cdn.jsdelivr.net`, the fallback cannot
  load; vendor the files locally so everything is same-origin.
* **Camera never starts but models load.** Separate issue: the page
  must be served over HTTPS (or localhost) for browser camera access.
