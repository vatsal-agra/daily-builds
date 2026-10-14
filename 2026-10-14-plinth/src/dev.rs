//! Block devices. `MemDev` can record every write/flush so a fuzzer can later rebuild any
//! disk state a real device is permitted to expose after power loss.
use crate::layout::*;
use std::io;
use std::os::unix::fs::FileExt;

pub trait BlockDev {
    fn nblocks(&self) -> u32;
    fn read(&mut self, b: u32, buf: &mut Block) -> io::Result<()>;
    fn write(&mut self, b: u32, buf: &Block) -> io::Result<()>;
    /// Barrier: everything written before this call is durable before anything written after it.
    fn flush(&mut self) -> io::Result<()>;
}

#[derive(Clone)]
pub enum Event {
    Write(u32, Box<Block>),
    Flush,
    /// Marker emitted by the fuzzer after an operation fully returned.
    Mark,
}

#[derive(Clone)]
pub struct MemDev {
    pub data: Vec<u8>,
    pub log: Option<Vec<Event>>,
    pub writes: u64,
    pub flushes: u64,
}

impl MemDev {
    pub fn new(nblocks: u32) -> MemDev {
        MemDev { data: vec![0; nblocks as usize * BS], log: None, writes: 0, flushes: 0 }
    }
    pub fn from_bytes(data: Vec<u8>) -> MemDev {
        MemDev { data, log: None, writes: 0, flushes: 0 }
    }
    pub fn start_recording(&mut self) {
        self.log = Some(Vec::new());
    }
    pub fn mark(&mut self) {
        if let Some(l) = self.log.as_mut() {
            l.push(Event::Mark);
        }
    }
}

fn oob(b: u32) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, format!("block {b} out of range"))
}

impl BlockDev for MemDev {
    fn nblocks(&self) -> u32 {
        (self.data.len() / BS) as u32
    }
    fn read(&mut self, b: u32, buf: &mut Block) -> io::Result<()> {
        let o = b as usize * BS;
        if o + BS > self.data.len() {
            return Err(oob(b));
        }
        buf.copy_from_slice(&self.data[o..o + BS]);
        Ok(())
    }
    fn write(&mut self, b: u32, buf: &Block) -> io::Result<()> {
        let o = b as usize * BS;
        if o + BS > self.data.len() {
            return Err(oob(b));
        }
        self.data[o..o + BS].copy_from_slice(buf);
        self.writes += 1;
        if let Some(l) = self.log.as_mut() {
            l.push(Event::Write(b, Box::new(*buf)));
        }
        Ok(())
    }
    fn flush(&mut self) -> io::Result<()> {
        self.flushes += 1;
        if let Some(l) = self.log.as_mut() {
            l.push(Event::Flush);
        }
        Ok(())
    }
}

pub struct FileDev {
    f: std::fs::File,
    n: u32,
    /// `PLINTH_NOSYNC=1` skips fsync (benchmarks and tests only; defeats durability).
    nosync: bool,
}

impl FileDev {
    pub fn open(path: &str) -> io::Result<FileDev> {
        let f = std::fs::OpenOptions::new().read(true).write(true).open(path)?;
        let len = f.metadata()?.len();
        if len % BS as u64 != 0 || len == 0 {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "image size is not a multiple of the block size"));
        }
        Ok(FileDev { f, n: (len / BS as u64) as u32, nosync: std::env::var_os("PLINTH_NOSYNC").is_some() })
    }
    pub fn create(path: &str, nblocks: u32) -> io::Result<FileDev> {
        let f = std::fs::OpenOptions::new().read(true).write(true).create(true).truncate(true).open(path)?;
        f.set_len(nblocks as u64 * BS as u64)?;
        Ok(FileDev { f, n: nblocks, nosync: std::env::var_os("PLINTH_NOSYNC").is_some() })
    }
}

impl BlockDev for FileDev {
    fn nblocks(&self) -> u32 {
        self.n
    }
    fn read(&mut self, b: u32, buf: &mut Block) -> io::Result<()> {
        if b >= self.n {
            return Err(oob(b));
        }
        self.f.read_exact_at(buf, b as u64 * BS as u64)
    }
    fn write(&mut self, b: u32, buf: &Block) -> io::Result<()> {
        if b >= self.n {
            return Err(oob(b));
        }
        self.f.write_all_at(buf, b as u64 * BS as u64)
    }
    fn flush(&mut self) -> io::Result<()> {
        if self.nosync {
            return Ok(());
        }
        self.f.sync_data()
    }
}

/// Wraps a device and makes the Nth write (1-based, counting from now) and every later one fail.
pub struct FaultDev<D: BlockDev> {
    pub inner: D,
    pub fail_at: Option<u64>,
    pub writes: u64,
}

impl<D: BlockDev> FaultDev<D> {
    pub fn new(inner: D) -> FaultDev<D> {
        FaultDev { inner, fail_at: None, writes: 0 }
    }
}

impl<D: BlockDev> BlockDev for FaultDev<D> {
    fn nblocks(&self) -> u32 {
        self.inner.nblocks()
    }
    fn read(&mut self, b: u32, buf: &mut Block) -> io::Result<()> {
        self.inner.read(b, buf)
    }
    fn write(&mut self, b: u32, buf: &Block) -> io::Result<()> {
        self.writes += 1;
        if let Some(n) = self.fail_at {
            if self.writes >= n {
                return Err(io::Error::new(io::ErrorKind::Other, "injected write failure"));
            }
        }
        self.inner.write(b, buf)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.inner.flush()
    }
}
