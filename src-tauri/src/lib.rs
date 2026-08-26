//! Tauri shell: window management + Python sidecar lifecycle (spec §3).
//!
//! The sidecar is the backend/ FastAPI service started as a child process on a
//! random loopback port. The port is surfaced to the UI through the
//! `sidecar_port` command so src/lib/api.ts can target it (no fixed ports).

use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Emitter, Manager};

struct SidecarState(Mutex<Option<Child>>);

#[tauri::command]
fn sidecar_port() -> Option<u16> {
    PORT.get().copied()
}

static PORT: std::sync::OnceLock<u16> = std::sync::OnceLock::new();

fn locate_python() -> Option<std::path::PathBuf> {
    // Prefer the project venv (spec §12 quickstart); fall back to PATH python.
    let venv = if cfg!(windows) {
        ["backend", ".venv", "Scripts", "python.exe"].iter().collect::<std::path::PathBuf>()
    } else {
        ["backend", ".venv", "bin", "python"].iter().collect::<std::path::PathBuf>()
    };
    if venv.exists() {
        Some(venv)
    } else {
        which_py()
    }
}

fn which_py() -> Option<std::path::PathBuf> {
    let candidates: &[&str] = if cfg!(windows) {
        &["python.exe", "py.exe"]
    } else {
        &["python3", "python"]
    };
    candidates.iter().find_map(|c| {
        Command::new(c)
            .arg("--version")
            .output()
            .ok()
            .filter(|o| o.status.success())
            .map(|_| std::path::PathBuf::from(c))
    })
}

fn spawn_sidecar(app: &tauri::AppHandle) -> Option<Child> {
    let python = locate_python()?;
    // Pick a free loopback port ourselves so the frontend never guesses.
    let port = portpicker::pick_unused_port().expect("no free loopback port");
    let backend_dir = std::env::current_dir()
        .map(|p| p.join("backend"))
        .unwrap_or_else(|_| std::path::PathBuf::from("backend"));

    // uvicorn entrypoint from backend/requirements.txt; cwd=backend because
    // core.* imports are relative to it (see tests/conftest.py rationale).
    let child = Command::new(&python)
        .args(["-m", "uvicorn", "main:app", "--host", "127.0.0.1",
               "--port", &port.to_string(), "--log-level", "info"])
        .current_dir(&backend_dir)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| eprintln!("sidecar spawn failed: {e}"))
        .ok();

    // Health-wait loop emits 'sidecar-ready' once /health responds.
    {
        let handle = app.clone();
        tauri::async_runtime::spawn(async move {
            let url = format!("http://127.0.0.1:{port}/health");
            for _ in 0..30 {
                if http_probe_ok(&url) {
                    let _ = PORT.set(port);
                    let _ = handle.emit("sidecar-ready", port);
                    return;
                }
                tokio_sleep(std::time::Duration::from_millis(250)).await;
            }
            eprintln!("sidecar did not become healthy within 7.5 s");
        });
    }
    child
}

// Minimal HTTP probe without adding an HTTP client dependency.
fn http_probe_ok(url: &str) -> bool {
    let mut cmd = Command::new(if cfg!(windows) { "powershell" } else { "curl" });
    if cfg!(windows) {
        let script =
            format!("try {{ (Invoke-WebRequest -UseBasicParsing -Uri '{url}' -TimeoutSec 2).StatusCode -eq 200 }} catch {{ $false }}");
        cmd.args(["-NoProfile", "-Command", script.as_str()]);
    } else {
        cmd.args(["-sf", url]);
    }
    cmd.creation_flags_hide_window()
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

trait HideWindow {
    fn creation_flags_hide_window(&mut self) -> &mut Self;
}
impl HideWindow for std::process::Command {
    fn creation_flags_hide_window(&mut self) -> &mut Self {
        #[cfg(windows)]
        use std::os::windows::process::CommandExt;
        #[cfg(windows)]
        self.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        self
    }
}

async fn tokio_sleep(dur: std::time::Duration) {
    std::thread::sleep(dur); // called only from our monitor task; cheap enough for M0
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let handle = app.handle().clone();
            match spawn_sidecar(&handle) {
                Some(child) => {
                    app.handle().manage(SidecarState(Mutex::new(Some(child))));
                }
                None => eprintln!("WARNING: no python found; running without transcription backend"),
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![sidecar_port])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // Graceful shutdown: kill the sidecar when the app exits (workflow doc:
            // sidecar lifecycle lives here so child processes never outlive the UI).
            if matches!(event, tauri::RunEvent::Exit) {
                if let Some(state) = app_handle.try_state::<SidecarState>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(child) = guard.as_mut() {
                            let _ = child.kill();
                        }
                    }
                }
            }
        });
}
