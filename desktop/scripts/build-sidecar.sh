#!/bin/sh
set -eu

desktop_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
workspace_root=$(CDPATH= cd -- "$desktop_root/.." && pwd)
venv="$desktop_root/.sidecar-venv"
build_root="$desktop_root/.sidecar-build"
dist_root="$desktop_root/.sidecar-dist"
runtime_root="$desktop_root/src-tauri/resources/sidecar-runtime"
launcher="$desktop_root/src-tauri/binaries/hermes-sidecar-aarch64-apple-darwin"
local_activity_payload="$workspace_root/domains/local_content/xingce/p031-data-analysis-v1.json"
python_bin=${PYTHON_BIN:-python3}

if [ "$(uname -m)" != "arm64" ]; then
  echo "Lumi macOS sidecar must be built on arm64; found $(uname -m)." >&2
  exit 1
fi

if [ ! -f "$local_activity_payload" ]; then
  echo "P0.3.1 local activity payload is missing; run domains/tools/import_xingce_local_bundle.py first." >&2
  exit 1
fi

rm -rf "$venv" "$build_root" "$dist_root" "$runtime_root"
"$python_bin" -m venv "$venv"

export PIP_CACHE_DIR="$desktop_root/.pip-cache"
export PYINSTALLER_CONFIG_DIR="$desktop_root/.pyinstaller-cache"
"$venv/bin/python" -m pip install \
  --disable-pip-version-check \
  --no-input \
  --upgrade \
  "pyinstaller==6.21.0" \
  "pypdf==6.10.0"
"$venv/bin/python" -c \
  'import PyInstaller, pypdf; assert PyInstaller.__version__ == "6.21.0"; assert pypdf.__version__ == "6.10.0"'

mkdir -p "$(dirname -- "$launcher")" "$runtime_root"

"$venv/bin/python" -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name hermes-sidecar \
  --target-architecture arm64 \
  --distpath "$dist_root" \
  --workpath "$build_root/work" \
  --specpath "$build_root/spec" \
  --paths "$workspace_root/service" \
  --paths "$workspace_root/integration" \
  --paths "$workspace_root/runtime" \
  --paths "$workspace_root/engine" \
  --paths "$workspace_root/domains" \
  --paths "$workspace_root/study_pack" \
  --collect-submodules hermes_service \
  --collect-submodules hermes_integration \
  --collect-submodules hermes_runtime \
  --collect-submodules hermes_kt \
  --collect-submodules hermes_domains \
  --collect-submodules lumi_study_pack \
  --collect-all pypdf \
  --add-data "$workspace_root/domains/fixtures:domains/fixtures" \
  --add-data "$workspace_root/domains/content:domains/content" \
  --add-data "$workspace_root/domains/released:domains/released" \
  --add-data "$workspace_root/domains/local_content:domains/local_content" \
  "$desktop_root/sidecars/hermes_sidecar_bootstrap.py"

cp -R "$dist_root/hermes-sidecar/." "$runtime_root/"
clang -arch arm64 -Os -Wall -Wextra -Werror \
  -o "$launcher" "$desktop_root/sidecars/hermes_sidecar_launcher.c"
file "$runtime_root/hermes-sidecar" | grep -q 'arm64'
file "$launcher" | grep -q 'arm64'
echo "Built packaged arm64 sidecar runtime: $runtime_root/hermes-sidecar"
