#!/bin/bash
# ============================================================================
#  build.sh — Build, tag, and push Odoo 18 Docker image to Docker Hub
#
#  Run from: the docker-deploy directory
#
#  IMPORTANT: Set your Docker Hub username below!
# ============================================================================

set -e

# ── CONFIGURATION ───────────────────────────────────────────────────────────
DOCKERHUB_USER="${DOCKERHUB_USER:-nandusaji}"
IMAGE_NAME="odoo18-custom"
IMAGE_TAG="latest"
FULL_IMAGE="${DOCKERHUB_USER}/${IMAGE_NAME}:${IMAGE_TAG}"

CUSTOM_ADDONS_DIR="${CUSTOM_ADDONS_DIR:-$(dirname "$(pwd)")}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "============================================================"
echo "  Odoo 18 Docker Image Builder + Push"
echo "============================================================"
echo ""
echo "  Docker Hub image: ${FULL_IMAGE}"
echo ""


# ── Step 1: Clean previous addons copy ────────────────────────────────────
if [ -d "$SCRIPT_DIR/addons" ]; then
    echo "[1/5] Cleaning previous addons copy..."
    rm -rf "$SCRIPT_DIR/addons"
fi

# ── Step 2: Copy custom addons into the build context ─────────────────────
echo "[2/5] Copying custom addons into build context..."
mkdir -p "$SCRIPT_DIR/addons"

for dir in \
    account-financial-reporting \
    base_territory \
    field-service \
    helpdesk \
    mis-builder \
    partner-contact \
    reporting-engine \
    server-tools \
    server-ux \
    social \
    stock-logistics-orderpoint \
    web \
    wms
do
    if [ -d "$CUSTOM_ADDONS_DIR/$dir" ]; then
        echo "       Copying $dir ..."
        cp -r "$CUSTOM_ADDONS_DIR/$dir" "$SCRIPT_DIR/addons/$dir"
    else
        echo "       WARNING: $dir not found in $CUSTOM_ADDONS_DIR, skipping."
    fi
done

# ── Step 3: Build the Docker image ────────────────────────────────────────
echo "[3/5] Building Docker image: ${IMAGE_NAME} ..."
docker build -t "$IMAGE_NAME" "$SCRIPT_DIR"

# ── Step 4: Tag the image ────────────────────────────────────────────────
echo "[4/5] Tagging image as ${FULL_IMAGE} ..."
docker tag "$IMAGE_NAME" "$FULL_IMAGE"

# ── Step 5: Push to Docker Hub ────────────────────────────────────────────
echo "[5/5] Pushing to Docker Hub..."
if ! docker push "$FULL_IMAGE"; then
    echo "[ERROR] Docker push failed! Make sure you are logged in:"
    echo "        docker login"
    exit 1
fi

echo ""
echo "============================================================"
echo "  SUCCESS! Image pushed to Docker Hub."
echo "============================================================"
echo ""
echo "  Image:        ${FULL_IMAGE}"
echo ""
echo "  Local test:   docker compose up -d"
echo "                then visit http://localhost:8069"
echo ""
echo "  Render:       Go to Render dashboard and trigger a"
echo "                manual deploy, or it will auto-detect."
echo ""
