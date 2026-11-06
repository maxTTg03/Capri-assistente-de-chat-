#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/main.py" ]]; then
    PROJECT_DIR="$SCRIPT_DIR"
else
    PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
fi

for command_name in python3 appimagetool; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Dependência ausente: %s\n' "$command_name" >&2
        exit 1
    fi
done

BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/capri-appimage.XXXXXX")"
trap 'rm -rf -- "$BUILD_DIR"' EXIT

python3 -m venv "$BUILD_DIR/venv"
"$BUILD_DIR/venv/bin/python" -m pip install --upgrade pip
"$BUILD_DIR/venv/bin/python" -m pip install \
    -r "$PROJECT_DIR/requirements.txt" pyinstaller

"$BUILD_DIR/venv/bin/python" -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --onedir \
    --name CAPRI \
    --add-data "$PROJECT_DIR/assets/capri.png:assets" \
    --add-data "$PROJECT_DIR/assets/animations:assets/animations" \
    --distpath "$BUILD_DIR/dist" \
    --workpath "$BUILD_DIR/work" \
    --specpath "$BUILD_DIR/spec" \
    "$PROJECT_DIR/main.py"

APP_DIR="$BUILD_DIR/CAPRI.AppDir"
mkdir -p "$APP_DIR/usr/bin"
cp -a "$BUILD_DIR/dist/CAPRI/." "$APP_DIR/usr/bin/"
cp "$PROJECT_DIR/assets/capri.png" "$APP_DIR/capri.png"
cp "$SCRIPT_DIR/capri.desktop" "$APP_DIR/capri.desktop"
cp "$SCRIPT_DIR/AppRun" "$APP_DIR/AppRun"
chmod +x "$APP_DIR/AppRun"

OUTPUT_DIR="$PROJECT_DIR/dist-linux"
mkdir -p "$OUTPUT_DIR"
ARCH="$(uname -m)"
OUTPUT="$OUTPUT_DIR/CAPRI-$ARCH.AppImage"
ARCH="$ARCH" appimagetool "$APP_DIR" "$OUTPUT"
printf 'AppImage criado: %s\n' "$OUTPUT"
