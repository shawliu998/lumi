#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    error::Error,
    fs,
    io::{self, Read, Write},
    net::{SocketAddr, TcpStream},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

use tauri::{async_runtime::Receiver, Manager, RunEvent};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

const SIDECAR_NAME: &str = "hermes-sidecar";
const SIDECAR_PORT: u16 = 8765;
const STARTUP_TIMEOUT: Duration = Duration::from_secs(8);

#[derive(Clone, Default)]
struct ManagedSidecar(Arc<Mutex<Option<RunningSidecar>>>);

struct RunningSidecar {
    child: Option<CommandChild>,
    events: Option<Receiver<CommandEvent>>,
}

impl RunningSidecar {
    fn terminate_and_wait(&mut self) {
        let Some(child) = self.child.take() else {
            return;
        };
        let pid = child.pid();
        if let Err(error) = child.kill() {
            eprintln!("failed to kill Lumi sidecar pid {pid}: {error}");
        }

        let Some(events) = self.events.take() else {
            eprintln!("Lumi sidecar pid {pid} had no termination receiver");
            return;
        };
        let terminated = tauri::async_runtime::block_on(async move {
            let mut events = events;
            while let Some(event) = events.recv().await {
                if matches!(event, CommandEvent::Terminated(_)) {
                    return true;
                }
            }
            false
        });
        if !terminated {
            eprintln!("Lumi sidecar pid {pid} closed without a termination event");
        }
    }
}

impl Drop for RunningSidecar {
    fn drop(&mut self) {
        self.terminate_and_wait();
    }
}

fn main() {
    let sidecar = ManagedSidecar::default();
    let setup_sidecar = sidecar.clone();
    let exit_sidecar = sidecar.clone();

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(move |app| {
            let child = start_sidecar(&app.handle())?;
            *setup_sidecar
                .0
                .lock()
                .map_err(|_| io::Error::other("sidecar lifecycle lock was poisoned"))? =
                Some(child);
            schedule_debug_exit_after_health(&app.handle());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Lumi desktop shell");

    app.run(move |_app, event| {
        if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
            stop_sidecar(&exit_sidecar);
        }
    });
}

fn start_sidecar(app: &tauri::AppHandle) -> Result<RunningSidecar, Box<dyn Error>> {
    let port = sidecar_port()?;
    ensure_sidecar_port_is_free(port)?;

    let app_data_directory = app.path().app_data_dir()?;
    fs::create_dir_all(&app_data_directory)?;
    let database = app_data_directory.join("sidecar.sqlite3");
    let database = database
        .to_str()
        .ok_or_else(|| io::Error::other("sidecar database path is not valid UTF-8"))?;
    let runtime_directory = app.path().resource_dir()?.join("sidecar-runtime");
    let runtime_directory = runtime_directory
        .to_str()
        .ok_or_else(|| io::Error::other("sidecar runtime path is not valid UTF-8"))?;
    let port_argument = port.to_string();

    let (events, child) = app
        .shell()
        .sidecar(SIDECAR_NAME)?
        .env("HERMES_SIDECAR_RUNTIME_DIR", runtime_directory)
        .args(["--db", database, "serve", "--port", &port_argument])
        .spawn()?;

    if let Err(error) = wait_for_sidecar_health(port) {
        let mut sidecar = RunningSidecar {
            child: Some(child),
            events: Some(events),
        };
        sidecar.terminate_and_wait();
        return Err(error.into());
    }

    Ok(RunningSidecar {
        child: Some(child),
        events: Some(events),
    })
}

fn sidecar_port() -> io::Result<u16> {
    #[cfg(debug_assertions)]
    if let Ok(value) = std::env::var("HERMES_SIDECAR_PORT") {
        let port = value.parse::<u16>().map_err(|_| {
            io::Error::new(
                io::ErrorKind::InvalidInput,
                "HERMES_SIDECAR_PORT must be a valid u16 port",
            )
        })?;
        if port == 0 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "HERMES_SIDECAR_PORT must not be zero",
            ));
        }
        return Ok(port);
    }
    Ok(SIDECAR_PORT)
}

fn ensure_sidecar_port_is_free(port: u16) -> io::Result<()> {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    if TcpStream::connect_timeout(&address, Duration::from_millis(100)).is_ok() {
        return Err(io::Error::new(
            io::ErrorKind::AddrInUse,
            format!("Lumi sidecar port {port} is already in use"),
        ));
    }
    Ok(())
}

fn wait_for_sidecar_health(port: u16) -> io::Result<()> {
    let deadline = Instant::now() + STARTUP_TIMEOUT;
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let mut last_error = None;

    while Instant::now() < deadline {
        match request_sidecar_health(address, port) {
            Ok(response) if valid_health_response(&response) => return Ok(()),
            Ok(_) => last_error = Some("unexpected health response".to_owned()),
            Err(error) => last_error = Some(error.to_string()),
        }
        thread::sleep(Duration::from_millis(100));
    }

    Err(io::Error::new(
        io::ErrorKind::TimedOut,
        format!(
            "Lumi sidecar did not complete a local health handshake: {}",
            last_error.unwrap_or_else(|| "unknown error".to_owned())
        ),
    ))
}

fn request_sidecar_health(address: SocketAddr, port: u16) -> io::Result<String> {
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_millis(250))?;
    stream.set_read_timeout(Some(Duration::from_millis(500)))?;
    stream.set_write_timeout(Some(Duration::from_millis(500)))?;
    let request =
        format!("GET /v1/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
    stream.write_all(request.as_bytes())?;
    let mut response = String::new();
    stream.read_to_string(&mut response)?;
    Ok(response)
}

fn valid_health_response(response: &str) -> bool {
    (response.starts_with("HTTP/1.0 200") || response.starts_with("HTTP/1.1 200"))
        && response.contains("\"status\":\"ok\"")
        && response.contains("\"service\":\"hermes-local-sidecar\"")
        && response.contains("\"local_only\":true")
}

fn stop_sidecar(state: &ManagedSidecar) {
    let sidecar = state.0.lock().ok().and_then(|mut state| state.take());
    if let Some(sidecar) = sidecar {
        stop_running_sidecar(sidecar);
    }
}

fn stop_running_sidecar(mut sidecar: RunningSidecar) {
    sidecar.terminate_and_wait();
}

#[cfg(debug_assertions)]
fn schedule_debug_exit_after_health(app: &tauri::AppHandle) {
    if std::env::var_os("HERMES_EXIT_AFTER_SIDECAR_HEALTH").is_none() {
        return;
    }
    let app = app.clone();
    thread::spawn(move || {
        thread::sleep(Duration::from_secs(4));
        app.exit(0);
    });
}

#[cfg(not(debug_assertions))]
fn schedule_debug_exit_after_health(_: &tauri::AppHandle) {}
