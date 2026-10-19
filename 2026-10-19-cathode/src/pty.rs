//! A pseudo-terminal and the child process attached to it. The libc entry points are bound by
//! hand (no `libc` crate); child setup uses `std::process::Command` with a `pre_exec` hook.
//! Linux only (ioctl request numbers are the Linux values).

use std::ffi::{c_char, c_int, c_ulong};
use std::fs::{File, OpenOptions};
use std::io::{self, Read, Write};
use std::os::fd::{AsRawFd, FromRawFd};
use std::os::unix::process::{CommandExt, ExitStatusExt};
use std::process::{Child, Command, ExitStatus, Stdio};

unsafe extern "C" {
    fn posix_openpt(flags: c_int) -> c_int;
    fn grantpt(fd: c_int) -> c_int;
    fn unlockpt(fd: c_int) -> c_int;
    fn ptsname_r(fd: c_int, buf: *mut c_char, len: usize) -> c_int;
    fn ioctl(fd: c_int, req: c_ulong, ...) -> c_int;
    fn setsid() -> c_int;
    fn poll(fds: *mut PollFd, n: c_ulong, timeout: c_int) -> c_int;
    fn kill(pid: c_int, sig: c_int) -> c_int;
    fn fcntl(fd: c_int, cmd: c_int, ...) -> c_int;
}

const O_RDWR: c_int = 2;
const O_NOCTTY: c_int = 0o400;
const TIOCGWINSZ: c_ulong = 0x5413;
const TIOCSWINSZ: c_ulong = 0x5414;
const TIOCSCTTY: c_ulong = 0x540E;
const POLLIN: i16 = 1;
const F_GETFL: c_int = 3;
const F_SETFL: c_int = 4;
const O_NONBLOCK: c_int = 0o4000;

#[repr(C)]
struct PollFd {
    fd: c_int,
    events: i16,
    revents: i16,
}

#[repr(C)]
#[derive(Default, Clone, Copy)]
struct WinSize {
    rows: u16,
    cols: u16,
    xpix: u16,
    ypix: u16,
}

pub struct Pty {
    master: File,
    child: Child,
    eof: bool,
}

pub struct SpawnOpts {
    pub cols: usize,
    pub rows: usize,
    pub env: Vec<(String, String)>,
    pub cwd: Option<String>,
}

impl Default for SpawnOpts {
    fn default() -> Self {
        SpawnOpts { cols: 80, rows: 24, env: Vec::new(), cwd: None }
    }
}

fn check(r: c_int) -> io::Result<c_int> {
    if r < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(r)
    }
}

impl Pty {
    pub fn spawn(argv: &[String], opts: &SpawnOpts) -> io::Result<Pty> {
        if argv.is_empty() {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, "empty command"));
        }
        // SAFETY: plain libc calls on a freshly created descriptor that we own and wrap in a File.
        let master = unsafe {
            let fd = check(posix_openpt(O_RDWR | O_NOCTTY))?;
            let master = File::from_raw_fd(fd);
            check(grantpt(fd))?;
            check(unlockpt(fd))?;
            master
        };
        let mut name = [0 as c_char; 128];
        // SAFETY: buffer and length are valid.
        check(unsafe { ptsname_r(master.as_raw_fd(), name.as_mut_ptr(), name.len()) })?;
        let path = unsafe { std::ffi::CStr::from_ptr(name.as_ptr()) }.to_string_lossy().into_owned();
        let slave = OpenOptions::new().read(true).write(true).custom_flags_noctty().open(&path)?;
        let ws = WinSize { rows: opts.rows as u16, cols: opts.cols as u16, xpix: 0, ypix: 0 };
        // SAFETY: ws is a valid winsize for the duration of the call.
        check(unsafe { ioctl(slave.as_raw_fd(), TIOCSWINSZ, &ws as *const WinSize) })?;

        let mut cmd = Command::new(&argv[0]);
        cmd.args(&argv[1..]);
        cmd.env("TERM", "xterm-256color").env("COLORTERM", "truecolor");
        cmd.env_remove("COLUMNS").env_remove("LINES");
        for (k, v) in &opts.env {
            cmd.env(k, v);
        }
        if let Some(d) = &opts.cwd {
            cmd.current_dir(d);
        }
        cmd.stdin(Stdio::from(slave.try_clone()?)).stdout(Stdio::from(slave.try_clone()?)).stderr(Stdio::from(slave));
        // SAFETY: the hook only calls async-signal-safe functions (setsid, ioctl).
        unsafe {
            cmd.pre_exec(|| {
                if setsid() < 0 {
                    return Err(io::Error::last_os_error());
                }
                if ioctl(0, TIOCSCTTY, 0 as c_int) < 0 {
                    return Err(io::Error::last_os_error());
                }
                Ok(())
            });
        }
        let child = cmd.spawn()?;
        drop(cmd); // closes the parent's copies of the slave
        // Non-blocking master: a stalled child must never wedge the host (see `try_write`).
        // SAFETY: plain fcntl on our own descriptor.
        unsafe {
            let fl = check(fcntl(master.as_raw_fd(), F_GETFL))?;
            check(fcntl(master.as_raw_fd(), F_SETFL, fl | O_NONBLOCK))?;
        }
        Ok(Pty { master, child, eof: false })
    }

    pub fn pid(&self) -> u32 {
        self.child.id()
    }

    /// Wait up to `ms` for output. `Ok(None)` = timeout; `Ok(Some(0))` = child side closed.
    pub fn read_timeout(&mut self, buf: &mut [u8], ms: i32) -> io::Result<Option<usize>> {
        if self.eof {
            return Ok(Some(0));
        }
        let mut pfd = PollFd { fd: self.master.as_raw_fd(), events: POLLIN, revents: 0 };
        // SAFETY: pfd is a valid single-element array.
        let r = unsafe { poll(&mut pfd as *mut PollFd, 1, ms) };
        if r < 0 {
            let e = io::Error::last_os_error();
            if e.kind() == io::ErrorKind::Interrupted {
                return Ok(None);
            }
            return Err(e);
        }
        if r == 0 {
            return Ok(None);
        }
        match self.master.read(buf) {
            Ok(0) => {
                self.eof = true;
                Ok(Some(0))
            }
            Ok(n) => Ok(Some(n)),
            Err(e) if e.raw_os_error() == Some(5) => {
                // EIO: every slave descriptor was closed (child exited).
                self.eof = true;
                Ok(Some(0))
            }
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => Ok(None),
            Err(e) => Err(e),
        }
    }

    /// Write as much of `data` as the PTY accepts right now. `Ok(0)` means the input queue is full.
    pub fn try_write(&mut self, data: &[u8]) -> io::Result<usize> {
        loop {
            match self.master.write(data) {
                Ok(n) => return Ok(n),
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => return Ok(0),
                Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
                Err(e) => return Err(e),
            }
        }
    }

    pub fn resize(&mut self, cols: usize, rows: usize) -> io::Result<()> {
        let ws = WinSize { rows: rows as u16, cols: cols as u16, xpix: 0, ypix: 0 };
        // SAFETY: valid fd and pointer.
        check(unsafe { ioctl(self.master.as_raw_fd(), TIOCSWINSZ, &ws as *const WinSize) })?;
        Ok(())
    }

    pub fn size(&self) -> io::Result<(usize, usize)> {
        let mut ws = WinSize::default();
        // SAFETY: valid fd and pointer.
        check(unsafe { ioctl(self.master.as_raw_fd(), TIOCGWINSZ, &mut ws as *mut WinSize) })?;
        Ok((ws.cols as usize, ws.rows as usize))
    }

    pub fn try_wait(&mut self) -> io::Result<Option<ExitStatus>> {
        self.child.try_wait()
    }

    pub fn wait(&mut self) -> io::Result<ExitStatus> {
        self.child.wait()
    }

    /// Send SIGKILL to the child's session/process group, then reap it.
    pub fn kill(&mut self) {
        let pid = self.child.id() as c_int;
        // SAFETY: signalling our own child; negative pid targets its process group (it called setsid).
        unsafe {
            kill(-pid, 9);
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for Pty {
    fn drop(&mut self) {
        if let Ok(None) = self.child.try_wait() {
            self.kill();
        }
    }
}

/// Human description of an exit status ("exit 3", "signal 9").
pub fn describe_status(s: &ExitStatus) -> String {
    match (s.code(), s.signal()) {
        (Some(c), _) => format!("exit {}", c),
        (None, Some(sig)) => format!("signal {}", sig),
        _ => "unknown".into(),
    }
}

trait OpenNoctty {
    fn custom_flags_noctty(&mut self) -> &mut Self;
}
impl OpenNoctty for OpenOptions {
    fn custom_flags_noctty(&mut self) -> &mut Self {
        use std::os::unix::fs::OpenOptionsExt;
        self.custom_flags(O_NOCTTY)
    }
}
