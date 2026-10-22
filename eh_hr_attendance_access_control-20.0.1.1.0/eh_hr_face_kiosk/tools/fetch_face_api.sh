#!/bin/sh
# ---------------------------------------------------------------------------
# fetch_face_api.sh
#
# One-command installer for the face-api.js library and model weights
# used by the Face Kiosk Attendance module (eh_hr_face_kiosk).
#
# The module deliberately does not vendor these files (about 6 MB; see
# static/lib/face-api/README.md for the rationale). This script pulls a
# pinned release into static/lib/face-api/ so the kiosk serves them
# locally and never needs the CDN fallback.
#
# Usage, from anywhere:
#
#   sh /path/to/eh_hr_face_kiosk/tools/fetch_face_api.sh
#
# Options:
#
#   --force      Redownload even if the files already exist.
#   --source X   Download base. One of:
#                  jsdelivr (default, pinned tag, immutable)
#                  github   (raw.githubusercontent.com, pinned tag)
#
# After it finishes, restart Odoo with the module updated:
#
#   ./odoo-bin -d <db> -u eh_hr_face_kiosk
#
# and hard-refresh the kiosk page (the ?v= asset stamp also bumps on
# its own once file mtimes change).
# ---------------------------------------------------------------------------
set -eu

PIN="0.22.2"
SOURCE="jsdelivr"
FORCE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --force) FORCE=1 ;;
        --source) shift; SOURCE="${1:-jsdelivr}" ;;
        -h|--help)
            sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
    shift
done

case "$SOURCE" in
    jsdelivr)
        LIB_URL="https://cdn.jsdelivr.net/gh/justadudewhohacks/face-api.js@${PIN}/dist/face-api.min.js"
        WEIGHTS_BASE="https://cdn.jsdelivr.net/gh/justadudewhohacks/face-api.js@${PIN}/weights"
        ;;
    github)
        LIB_URL="https://raw.githubusercontent.com/justadudewhohacks/face-api.js/${PIN}/dist/face-api.min.js"
        WEIGHTS_BASE="https://raw.githubusercontent.com/justadudewhohacks/face-api.js/${PIN}/weights"
        ;;
    *) echo "Unknown --source: $SOURCE (jsdelivr or github)" >&2; exit 2 ;;
esac

# Resolve the module's static/lib/face-api directory relative to this
# script, so the script works no matter where the addons path lives.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEST="${SCRIPT_DIR}/../static/lib/face-api"
MODELS="${DEST}/models"

MODEL_FILES="
tiny_face_detector_model-weights_manifest.json
tiny_face_detector_model-shard1
face_landmark_68_model-weights_manifest.json
face_landmark_68_model-shard1
face_recognition_model-weights_manifest.json
face_recognition_model-shard1
face_recognition_model-shard2
"

mkdir -p "$MODELS"

fetch() {
    # fetch <url> <dest-path>
    url="$1"; out="$2"
    if [ -s "$out" ] && [ "$FORCE" -eq 0 ]; then
        echo "  keep   $(basename "$out") (exists, use --force to redownload)"
        return 0
    fi
    echo "  fetch  $(basename "$out")"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 3 -o "${out}.part" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "${out}.part" "$url"
    else
        echo "Neither curl nor wget found. Install one and retry." >&2
        exit 3
    fi
    if [ ! -s "${out}.part" ]; then
        rm -f "${out}.part"
        echo "Downloaded file is empty: $url" >&2
        exit 4
    fi
    mv "${out}.part" "$out"
}

echo "face-api.js ${PIN} -> ${DEST}"
echo "source: ${SOURCE}"
echo

fetch "$LIB_URL" "${DEST}/face-api.min.js"
for f in $MODEL_FILES; do
    fetch "${WEIGHTS_BASE}/${f}" "${MODELS}/${f}"
done

echo
echo "Validating..."
FAIL=0

# Every file must be non-empty.
for f in face-api.min.js; do
    [ -s "${DEST}/${f}" ] || { echo "  MISSING ${f}"; FAIL=1; }
done
for f in $MODEL_FILES; do
    [ -s "${MODELS}/${f}" ] || { echo "  MISSING models/${f}"; FAIL=1; }
done

# Manifests must parse as JSON (a 404 page saved to disk is the classic
# failure mode). Use python3 when available, otherwise a cheap check
# that the first byte is '[' or '{'.
for m in tiny_face_detector_model-weights_manifest.json \
         face_landmark_68_model-weights_manifest.json \
         face_recognition_model-weights_manifest.json; do
    p="${MODELS}/${m}"
    [ -s "$p" ] || continue
    if command -v python3 >/dev/null 2>&1; then
        python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$p" 2>/dev/null \
            || { echo "  NOT JSON models/${m} (probably a saved error page)"; FAIL=1; }
    else
        head -c 1 "$p" | grep -q '[[{]' \
            || { echo "  NOT JSON models/${m} (probably a saved error page)"; FAIL=1; }
    fi
done

if [ "$FAIL" -ne 0 ]; then
    echo
    echo "Validation FAILED. Fix the items above and rerun (add --force)." >&2
    exit 5
fi

echo "  all files present and manifests parse as JSON"
echo
echo "Done. Restart Odoo with: ./odoo-bin -d <db> -u eh_hr_face_kiosk"
echo "Then hard-refresh the kiosk page."
