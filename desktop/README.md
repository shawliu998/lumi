# Lumi desktop

This directory is a Tauri 2 macOS wrapper for the Lumi client. Desktop build
commands first build `../client`, then package that exact output together with
the local sidecar so a stale frontend cannot be shipped accidentally.

## Prerequisites

- macOS with Xcode Command Line Tools
- Node.js 22+ and npm
- Rust stable (`rustup` is sufficient)

The npm scripts add `~/.cargo/bin` for their own process, so a rustup install
does not require a shell-profile change. They also keep npm's download cache in
`desktop/.npm-cache`, rather than writing into the frontend directory.

Install desktop dependencies:

```sh
cd $HOME/Documents/zhishixingqiu/desktop
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

Build a local release package, including the frontend and sidecar:

```sh
cd $HOME/Documents/zhishixingqiu/desktop && npm run build
```

For a quick locally unsigned macOS `.app` build (also builds the frontend):

```sh
npm run build:fast-app
```

Use the full rebuild when sidecar or question-bank source changed:

```sh
npm run build:debug-app
```

When the packaged sidecar is already current, create an installable local
release `.app` and `.dmg` without rebuilding PyInstaller:

```sh
npm run build:fast-release
```

Artifacts are emitted under `src-tauri/target/<profile>/bundle/`.

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

## Core-320 packaging

`npm run build:sidecar` packages the frozen `domains/practice_v3` manifest,
schema, and safe samples together with the deterministic generators. Before
starting PyInstaller it runs the non-writing `core320_bank` gate, so an invalid
digest or an unsafe materialization boundary fails before the expensive build.
The sidecar check fails closed unless its capability response matches the source
manifest's exact bank ID, version, SHA-256 digest, 320-question count, four
80-question module scopes, and one 320-question mixed scope. The managed-app
check additionally requires byte-identical manifest, schema, and safe-sample
files in the source tree, built runtime, and `.app`, then proves that Tauri
launches and stops the bundled sidecar. A missing runtime or `.app` is
`PENDING` in the consolidated evaluation harness, never a packaging pass.
These checks establish local ARM64 mechanics only; they do not establish
signing, notarization, universal-binary support, human content approval, or
external distribution readiness.
