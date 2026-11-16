#!/bin/bash
# Builds dist/HudsonActivity.app (menu-bar only, no Dock icon) with a free ad-hoc signature.
# Usage (from this folder):  ./build_macos.sh
set -euo pipefail
cd "$(dirname "$0")"

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt pyinstaller

.venv/bin/python -m PyInstaller --noconfirm --clean --windowed \
    --name HudsonActivity \
    --osx-bundle-identifier com.hudsonsoftwares.activity \
    --hidden-import pystray._darwin \
    run_agent.py

APP=dist/HudsonActivity.app
# Menu-bar app: hide the Dock icon.
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$APP/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :LSUIElement true" "$APP/Contents/Info.plist"
# Free ad-hoc signature (required to run on Apple Silicon). Replace "-" with a
# "Developer ID Application: ..." identity later to remove Gatekeeper warnings.
codesign --force --deep --sign - "$APP"

echo "Built: $(pwd)/$APP"
