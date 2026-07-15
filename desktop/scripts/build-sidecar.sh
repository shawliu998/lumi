#!/bin/sh
set -eu

desktop_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
workspace_root=$(CDPATH= cd -- "$desktop_root/.." && pwd)
venv="$desktop_root/.sidecar-venv"
build_root="$desktop_root/.sidecar-build"
dist_root="$desktop_root/.sidecar-dist"
runtime_root="$desktop_root/src-tauri/resources/sidecar-runtime"
launcher="$desktop_root/src-tauri/binaries/hermes-sidecar-aarch64-apple-darwin"
python_bin=${PYTHON_BIN:-python3}

if [ "$(uname -m)" != "arm64" ]; then
  echo "Lumi macOS sidecar must be built on arm64; found $(uname -m)." >&2
  exit 1
fi

# Fail before the expensive PyInstaller step if the source manifest, generated
# bank, or outside-Git materialization boundary is inconsistent.
"$python_bin" "$workspace_root/evals/run_all.py" --gate core320_bank --no-write

if [ ! -x "$venv/bin/python" ]; then
  "$python_bin" -m venv "$venv"
fi

export PIP_CACHE_DIR="$desktop_root/.pip-cache"
export PYINSTALLER_CONFIG_DIR="$desktop_root/.pyinstaller-cache"
"$venv/bin/python" -m pip install --disable-pip-version-check --upgrade "pyinstaller==6.21.0"

rm -rf "$build_root" "$dist_root" "$runtime_root"
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
  --collect-submodules hermes_service \
  --collect-submodules hermes_integration \
  --collect-submodules hermes_runtime \
  --collect-submodules hermes_kt \
  --collect-submodules hermes_practice \
  --collect-submodules hermes_domains \
  --add-data "$workspace_root/domains/fixtures:domains/fixtures" \
  --add-data "$workspace_root/domains/lessons:domains/lessons" \
  --add-data "$workspace_root/domains/practice_v2:domains/practice_v2" \
  --add-data "$workspace_root/domains/practice_v3:domains/practice_v3" \
  "$desktop_root/sidecars/hermes_sidecar_bootstrap.py"

cp -R "$dist_root/hermes-sidecar/." "$runtime_root/"
clang -arch arm64 -Os -Wall -Wextra -Werror \
  -o "$launcher" "$desktop_root/sidecars/hermes_sidecar_launcher.c"
file "$runtime_root/hermes-sidecar" | grep -q 'arm64'
file "$launcher" | grep -q 'arm64'
echo "Built packaged arm64 sidecar runtime: $runtime_root/hermes-sidecar"
