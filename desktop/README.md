# Lumi desktop

This directory is a Tauri 2 macOS wrapper for the existing
`../client/dist` frontend. It intentionally does not build or modify the
frontend: the UI owner controls `client/`, while this shell packages its latest
already-built output.

## Prerequisites

- macOS with Xcode Command Line Tools
- Node.js 22+ and npm
- Rust stable (`rustup` is sufficient)

The npm scripts add `~/.cargo/bin` for their own process, so a rustup install
does not require a shell-profile change. They also keep npm's download cache in
`desktop/.npm-cache`, rather than writing into the frontend directory.

Install desktop dependencies:

```sh
cd $HOME/Documents/peikao/desktop
npm_config_cache="$PWD/.npm-cache" npm install
```

## Commands

Build the arm64 Python sidecar in a freshly recreated, desktop-only virtual
environment. The build pins PyInstaller 6.21.0 and pypdf 6.10.0, then packages
the Study Pack domain and its isolated PDF worker into the onedir runtime:

```sh
npm run build:sidecar
```

Validate the wrapper configuration, packaged sidecar health handshake, and
sidecar termination:

```sh
npm run check:sidecar
```

For development, start the frontend in one terminal, then the Tauri shell in a
second. The development URL is loopback-only (`127.0.0.1:1420`).

```sh
# terminal 1, from desktop/
npm run dev:frontend

# terminal 2, from desktop/
npm run dev
```

Before a release build, the UI owner must build the frontend from `client/`:

```sh
cd $HOME/Documents/peikao/client && npm run build
cd $HOME/Documents/peikao/desktop && npm run build
```

For a local debug macOS `.app` verification build:

```sh
npm run build:debug-app
```

Artifacts are emitted under `src-tauri/target/<profile>/bundle/`. The debug-app
command rebuilds and checks the staged sidecar, builds the Tauri bundle, signs
every nested Mach-O and the final bundle with an ad-hoc identity, requires
strict/deep verification, and finally runs the bundle-resident check without
mutating the signed app. The signing script reports a stable file count by
default; pass `--verbose` directly to it only for per-file diagnostics. This is
a local integrity gate, not Developer ID signing or notarization. Recheck an
existing debug artifact with:

```sh
npm run check:signature
npm run check:bundled-sidecar
```

`check:bundled-sidecar` starts the exact bundle-resident launcher/runtime and
rechecks version 0.3.0, the closed `local-cited-study-pack-v1` capability, and
the pasted-text plus real text-bearing PDF lifecycle through create, review,
publish, citation, redacted launch, explicit non-learner test input, receipt
replay, and process restart. It hashes all existing learning/scheduling tables
before and after the flow, verifies they are unchanged, isolates
HOME/cache/temp/pycache, proves the frozen pypdf 6.10.0 path, and fails if the
signed `.app` content tree or root mtime changes. Its evidence contains only
counts, hashes, stable flags, and versions—never source or answer text. Public
batch/demo runs and evaluation learning modes are not advertised by the product
sidecar.

The staged/bundled harness sets the private
`LUMI_INTERNAL_STUDY_PACK_ATTEMPT_ORIGIN=evaluation_fixture` process variable;
HTTP cannot set or override it. The check requires every saved Study Pack test
attempt to use `evaluation_fixture` and verifies the isolated SQLite database
contains exactly zero `human_local_interactive` Study Pack attempts.

After a debug app build, verify that Tauri itself starts the packaged sidecar,
waits for its health handshake, and terminates it when Lumi quits:

```sh
npm run check:managed-app
```

That verification uses an ephemeral database plus debug-only port, self-exit,
and frozen-worker timeout hooks. It proves graceful and abrupt exit,
occupied-port failure, and startup timeout all reap the sidecar/PDF worker.
It explicitly removes the private evaluation-origin variable and proves the
managed product sidecar's launch contract defaults to `human_local_interactive`
without submitting an answer. Release builds always use port 8765 and do not
include those hooks.

## Security posture

- Product name: `Lumi`; bundle identifier: `com.lumi.learning`.
- Debug bundles are reproducibly ad-hoc signed and strict/deep verified after
  the sidecar and UI resources are final. They are not notarized distribution
  artifacts.
- Tauri uses a single `main` window and the base `core:default` capability only.
  The frontend has no Shell capability. Rust uses the shell plugin solely to
  launch the fixed, bundled `hermes-sidecar` executable and kill that child on
  application exit.
- The packaged sidecar is an arm64 PyInstaller onedir runtime built from the
  existing `service` implementation without modifying it. A fixed arm64 Tauri
  launcher `exec`s that runtime, preserving a single managed child PID. It
  receives only `--db <app-data>/sidecar.sqlite3 serve --port 8765`; the
  service itself rejects every non-loopback bind address.
- Startup fails closed unless `GET http://127.0.0.1:8765/v1/health` returns the
  expected local-only Lumi payload. If port 8765 is already occupied, Lumi
  does not attach to that process.
- The CSP defaults to `self`; its only explicitly allowed network endpoint is
  `http://127.0.0.1:8765`. There are no remote connection permissions.

The wrapper must continue consuming versioned frontend outputs; it must not
reach into mutable learning data or external production repositories.
