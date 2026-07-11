#!/bin/sh
set -eu

# rustup normally adds this path through a shell profile. Keep the wrapper
# self-contained so installation can remain profile-free.
if [ -x "$HOME/.cargo/bin/cargo" ]; then
  export PATH="$HOME/.cargo/bin:$PATH"
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export npm_config_cache="$(dirname -- "$script_dir")/.npm-cache"

exec npm exec tauri -- "$@"
