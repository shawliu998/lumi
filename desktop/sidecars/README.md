# Lumi local runtime sidecar

`npm run build:sidecar` builds the existing loopback-only `service` runtime as
an arm64 PyInstaller onedir executable tree. The build uses a virtual environment,
pip cache, PyInstaller work directory, and distribution directory under
`desktop/`; it reads the service and shared Python packages without modifying
them.

The output is intentionally named for Tauri's target-triple convention:

```text
src-tauri/resources/sidecar-runtime/hermes-sidecar
```

The onedir layout avoids PyInstaller's one-file supervisor/worker split, which
would make the Python worker untrackable. Tauri bundles the runtime tree as a
resource and an arm64 `externalBin` launcher at
`src-tauri/binaries/hermes-sidecar-aarch64-apple-darwin`. The launcher performs
`exec` into the resource executable, so Tauri retains the actual sidecar PID.
At runtime, Rust passes only the resource path, app-data SQLite location, and
port 8765. It first rejects an already occupied port, then requires
`GET /v1/health` to return the expected `local_only` Lumi response. The
process is retained as a managed child, killed, and waited on for
`ExitRequested` or `Exit`.

The Python bootstrap also runs a parent-death watchdog. If the managed parent
PID disappears or it is reparented to PID 1, the sidecar sends itself SIGTERM.
This is defense in depth; it does not replace Rust's normal kill-and-wait path.

The frontend never receives a Shell capability and cannot execute this or any
other command. No arbitrary executable, filesystem, or remote network access
is granted. The shell plugin is used only by trusted Rust lifecycle code.

`npm run check:sidecar` exercises the packed executable's health endpoint and
termination behavior. `npm run check:managed-app` performs the same lifecycle
verification through the built Tauri app.
