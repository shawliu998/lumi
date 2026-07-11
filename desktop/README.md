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

Build the arm64 Python sidecar in an isolated desktop-only virtual environment:

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
command rebuilds and checks the staged sidecar, builds the Tauri bundle, runs a
bundle-resident check that proves the app tree is unchanged, then signs every
nested Mach-O and the final bundle with an ad-hoc identity and requires strict
deep verification to pass. The signing script reports a stable file count by
default; pass `--verbose` directly to it only for per-file diagnostics. This is
a local integrity gate, not Developer ID signing or notarization. Recheck an
existing debug artifact with:

```sh
npm run check:signature
npm run check:bundled-sidecar
```

`check:bundled-sidecar` starts the exact bundle-resident launcher/runtime and
rechecks its version, bounded catalog capability, termination, closed opaque
run/command identifier profiles, and PII/secret identifier rejection. It also
isolates HOME/cache/temp/pycache and fails if the `.app` content tree or root
mtime changes. Public batch/demo runs and evaluation learning modes are not
advertised by the product sidecar.

After a debug app build, verify that Tauri itself starts the packaged sidecar,
waits for its health handshake, and terminates it when Lumi quits:

```sh
npm run check:managed-app
```

That verification uses ephemeral debug-only port and self-exit hooks, so it
does not interfere with an existing local process. Release builds always use
port 8765 and do not include either hook.

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
