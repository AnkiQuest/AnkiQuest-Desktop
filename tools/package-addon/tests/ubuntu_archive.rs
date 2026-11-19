//! Exercise the Ubuntu CI helper with real HTTP redirects and curl, without sudo.
#![cfg(target_os = "linux")]

use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::net::TcpListener;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::{Command, Output};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread::{self, JoinHandle};
use std::time::Duration;

const REDIRECT: &str = "HTTP/1.1 301 Moved Permanently\r\nLocation: /unavailable\r\n";
const HEALTHY: &str = "HTTP/1.1 200 OK\r\n";
const UNAVAILABLE: &str = "HTTP/1.1 503 Service Unavailable\r\n";

struct Mirrors {
    base: String,
    stop: Arc<AtomicBool>,
    redirected: Arc<AtomicBool>,
    worker: Option<JoinHandle<()>>,
}

impl Mirrors {
    fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        listener.set_nonblocking(true).unwrap();
        let stop = Arc::new(AtomicBool::new(false));
        let redirected = Arc::new(AtomicBool::new(false));
        let done = Arc::clone(&stop);
        let followed = Arc::clone(&redirected);
        let worker = thread::spawn(move || {
            while !done.load(Ordering::Relaxed) {
                let (mut stream, _) = match listener.accept() {
                    Ok(connection) => connection,
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(5));
                        continue;
                    }
                    Err(error) => panic!("{error}"),
                };
                stream
                    .set_read_timeout(Some(Duration::from_secs(1)))
                    .unwrap();
                let mut request = String::new();
                BufReader::new(&mut stream).read_line(&mut request).unwrap();
                let url = request.split_whitespace().nth(1).unwrap();
                let status = if url.starts_with("/redirect/") {
                    REDIRECT
                } else if url.starts_with("/healthy/") {
                    HEALTHY
                } else {
                    followed.store(url == "/unavailable", Ordering::Relaxed);
                    UNAVAILABLE
                };
                write!(
                    stream,
                    "{status}Content-Length: 0\r\nConnection: close\r\n\r\n"
                )
                .unwrap();
            }
        });
        Self {
            base,
            stop,
            redirected,
            worker: Some(worker),
        }
    }
}

impl Drop for Mirrors {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        self.worker.take().unwrap().join().unwrap();
    }
}

fn select(directory: &Path, mirrors: &[String]) -> Output {
    // Capture selection and apt verification without writing /etc or installing packages.
    let sudo = directory.join("sudo");
    fs::write(&sudo, "#!/usr/bin/env bash\nset -euo pipefail\ncase \"$1\" in\n    tee) cat > \"$RUNNER_TEMP/selected\" ;;\n    apt-get) printf '%s\\n' \"$*\" >> \"$RUNNER_TEMP/apt\" ;;\n    *) exit 99 ;;\nesac\n").unwrap();
    fs::set_permissions(sudo, fs::Permissions::from_mode(0o755)).unwrap();
    let paths = std::iter::once(directory.to_path_buf())
        .chain(std::env::split_paths(&std::env::var_os("PATH").unwrap()))
        .collect::<Vec<_>>();
    let selector =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../.github/scripts/ubuntu-archive.sh");
    Command::new("bash")
        .arg(selector)
        .args(mirrors)
        .env("PATH", std::env::join_paths(paths).unwrap())
        .env("RUNNER_TEMP", directory)
        .output()
        .unwrap()
}

#[test]
fn follow_redirect_before_selecting() {
    let mirrors = Mirrors::start();
    let redirect = format!("{}/redirect", mirrors.base);
    let healthy = format!("{}/healthy", mirrors.base);
    let fallback = tempfile::tempdir().unwrap();
    let result = select(fallback.path(), &[redirect.clone(), healthy.clone()]);
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    assert_eq!(
        fs::read_to_string(fallback.path().join("selected")).unwrap(),
        format!("{healthy}/\n")
    );
    assert!(mirrors.redirected.load(Ordering::Relaxed));
    assert!(
        fs::read_to_string(fallback.path().join("apt"))
            .unwrap()
            .contains("Error-Mode=any")
    );

    let unavailable = tempfile::tempdir().unwrap();
    let result = select(unavailable.path(), &[redirect]);
    assert_eq!(result.status.code(), Some(1));
    assert!(!unavailable.path().join("selected").exists());
    assert!(!unavailable.path().join("apt").exists());
}
