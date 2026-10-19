//! A live session: a child process on a PTY, a [`Term`] consuming its output, replies written
//! back to the child, optional asciicast recording, and a scripted-input runner.

use crate::cast::{Cast, Event, Utf8Chunker};
use crate::input::{encode_key, Item};
use crate::pty::{Pty, SpawnOpts};
use crate::term::Term;
use std::io;
use std::process::ExitStatus;
use std::time::{Duration, Instant};

pub struct Session {
    pub term: Term,
    pty: Pty,
    pub cast: Option<Cast>,
    pub record_input: bool,
    chunker: Utf8Chunker,
    start: Instant,
    pub exit: Option<ExitStatus>,
    eof: bool,
    /// Total bytes the child has written.
    pub bytes_read: u64,
}

impl Session {
    pub fn spawn(argv: &[String], opts: &SpawnOpts, record: bool) -> io::Result<Session> {
        let pty = Pty::spawn(argv, opts)?;
        let mut term = Term::new(opts.cols, opts.rows);
        term.screen.scrollback_limit = 10_000;
        let cast = if record {
            let mut c = Cast::new(opts.cols, opts.rows);
            c.command = Some(argv.join(" "));
            Some(c)
        } else {
            None
        };
        Ok(Session { term, pty, cast, record_input: false, chunker: Utf8Chunker::default(), start: Instant::now(), exit: None, eof: false, bytes_read: 0 })
    }

    fn now(&self) -> f64 {
        self.start.elapsed().as_secs_f64()
    }

    pub fn is_alive(&self) -> bool {
        !self.eof
    }

    fn record(&mut self, kind: char, data: String) {
        let t = self.now();
        if let Some(c) = &mut self.cast {
            if !data.is_empty() {
                c.events.push(Event { t, kind, data });
            }
        }
    }

    /// Read at most one chunk (waiting up to `ms`), feed it to the terminal and send back replies.
    /// Returns `Ok(true)` if data arrived, `Ok(false)` on timeout or EOF.
    pub fn pump(&mut self, ms: i32) -> io::Result<bool> {
        if self.eof {
            return Ok(false);
        }
        let mut buf = [0u8; 65536];
        match self.pty.read_timeout(&mut buf, ms)? {
            None => Ok(false),
            Some(0) => {
                self.eof = true;
                let rest = self.chunker.finish();
                self.record('o', rest);
                self.reap();
                Ok(false)
            }
            Some(n) => {
                self.bytes_read += n as u64;
                self.term.feed(&buf[..n]);
                let text = self.chunker.push(&buf[..n]);
                self.record('o', text);
                let reply = self.term.take_output();
                if !reply.is_empty() {
                    // the child may already be gone; a failed reply write is not an error
                    let _ = self.pty.write_all(&reply);
                }
                Ok(true)
            }
        }
    }

    fn reap(&mut self) {
        if self.exit.is_none() {
            // The child closed the PTY; give it a moment to be reapable.
            for _ in 0..200 {
                if let Ok(Some(st)) = self.pty.try_wait() {
                    self.exit = Some(st);
                    return;
                }
                std::thread::sleep(Duration::from_millis(5));
            }
        }
    }

    /// Pump until no output has arrived for `idle_ms`, the child exits, or `max_ms` elapse.
    pub fn pump_until_idle(&mut self, idle_ms: u64, max_ms: u64) -> io::Result<()> {
        let deadline = Instant::now() + Duration::from_millis(max_ms);
        loop {
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() || self.eof {
                return Ok(());
            }
            let wait = (idle_ms as u128).min(left.as_millis()) as i32;
            if !self.pump(wait.max(1))? {
                return Ok(());
            }
        }
    }

    /// Pump until the visible screen (or scrollback) contains `needle`. False on timeout/exit.
    pub fn wait_for_text(&mut self, needle: &str, timeout_ms: u64) -> io::Result<bool> {
        let deadline = Instant::now() + Duration::from_millis(timeout_ms);
        loop {
            if self.screen_contains(needle) {
                return Ok(true);
            }
            let left = deadline.saturating_duration_since(Instant::now());
            if left.is_zero() || self.eof {
                return Ok(self.screen_contains(needle));
            }
            self.pump((left.as_millis() as i32).min(50).max(1))?;
        }
    }

    pub fn screen_contains(&self, needle: &str) -> bool {
        self.term.screen.text().contains(needle)
    }

    pub fn send(&mut self, bytes: &[u8]) -> io::Result<()> {
        if self.record_input {
            let s = String::from_utf8_lossy(bytes).into_owned();
            self.record('i', s);
        }
        self.pty.write_all(bytes)
    }

    pub fn resize(&mut self, cols: usize, rows: usize) -> io::Result<()> {
        self.pty.resize(cols, rows)?;
        self.term.resize(cols, rows);
        self.record('r', format!("{}x{}", cols, rows));
        Ok(())
    }

    /// Run an input script. `until_timeout_ms` bounds each `<until "...">`.
    /// Errors if an `until` never matched (the script cannot continue meaningfully).
    pub fn run_script(&mut self, items: &[Item], until_timeout_ms: u64, key_delay_ms: u64) -> Result<(), String> {
        for it in items {
            match it {
                Item::Text(t) => {
                    self.send(t.as_bytes()).map_err(|e| e.to_string())?;
                    self.pump_until_idle(key_delay_ms.max(1), 2000).map_err(|e| e.to_string())?;
                }
                Item::Key(k, m) => {
                    let b = encode_key(&self.term.screen.modes, k, *m);
                    self.send(&b).map_err(|e| e.to_string())?;
                    self.pump_until_idle(key_delay_ms.max(1), 2000).map_err(|e| e.to_string())?;
                }
                Item::Wait(ms) => {
                    let deadline = Instant::now() + Duration::from_millis(*ms);
                    while Instant::now() < deadline && !self.eof {
                        let left = deadline.saturating_duration_since(Instant::now()).as_millis() as i32;
                        self.pump(left.max(1)).map_err(|e| e.to_string())?;
                    }
                    if self.eof && Instant::now() < deadline {
                        std::thread::sleep(deadline.saturating_duration_since(Instant::now()));
                    }
                }
                Item::Until(text) => {
                    if !self.wait_for_text(text, until_timeout_ms).map_err(|e| e.to_string())? {
                        return Err(format!("timed out after {} ms waiting for {:?}\n--- screen ---\n{}", until_timeout_ms, text, self.term.screen.text()));
                    }
                }
                Item::Resize(c, r) => {
                    self.resize(*c, *r).map_err(|e| e.to_string())?;
                    self.pump_until_idle(key_delay_ms.max(1), 2000).map_err(|e| e.to_string())?;
                }
            }
        }
        Ok(())
    }

    /// Give the child `grace_ms` to exit on its own, then kill it. Returns its exit status if it exited by itself.
    pub fn finish(&mut self, grace_ms: u64) -> Option<ExitStatus> {
        let _ = self.pump_until_idle(50, grace_ms);
        if self.exit.is_none() {
            if let Ok(Some(st)) = self.pty.try_wait() {
                self.exit = Some(st);
            }
        }
        if self.exit.is_none() {
            self.pty.kill();
        }
        self.exit
    }
}
