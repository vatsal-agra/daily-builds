//! Write-ahead journal: one transaction at a time, full data journaling.
//!
//! Commit protocol (each `flush` is a hardware barrier):
//! ```text
//!   1. write  descriptor + data blocks + commit block into the journal area
//!   2. flush                      -- the transaction is now durable (or provably incomplete via CRC)
//!   3. write  every block to its home location (checkpoint)
//!   4. flush
//!   5. write  zeros over the descriptor (retire the transaction)
//!   6. flush
//! ```
//! Recovery re-applies a transaction iff descriptor and commit agree on `seq` and the CRC over the
//! sequence number, target list and all data blocks matches. Re-applying is idempotent.
use crate::dev::BlockDev;
use crate::layout::*;
use std::collections::BTreeMap;
use std::io;

/// Deliberate protocol defects, used by the mutation self-test to prove the crash fuzzer has teeth.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Bug {
    None,
    /// Recovery trusts the commit block without verifying the CRC.
    NoCrc,
    /// Missing barrier between journal write and checkpoint.
    NoJournalFlush,
    /// Descriptor is retired *before* the checkpoint is durable.
    EarlyClear,
    /// Mount does not replay the journal at all.
    SkipReplay,
}

impl Bug {
    pub fn parse(s: &str) -> Option<Bug> {
        Some(match s {
            "none" => Bug::None,
            "no-crc" => Bug::NoCrc,
            "no-journal-flush" => Bug::NoJournalFlush,
            "early-clear" => Bug::EarlyClear,
            "skip-replay" => Bug::SkipReplay,
            _ => return None,
        })
    }
    pub const ALL_MUTANTS: [Bug; 4] = [Bug::NoCrc, Bug::NoJournalFlush, Bug::EarlyClear, Bug::SkipReplay];
    pub fn name(self) -> &'static str {
        match self {
            Bug::None => "none",
            Bug::NoCrc => "no-crc",
            Bug::NoJournalFlush => "no-journal-flush",
            Bug::EarlyClear => "early-clear",
            Bug::SkipReplay => "skip-replay",
        }
    }
}

pub fn max_tx_blocks(sb: &Superblock) -> usize {
    ((sb.journal_len - 2) as usize).min(JDESC_CAP)
}

fn tx_crc(seq: u64, targets: &[u32], datas: &[&Block]) -> u32 {
    let mut c = Crc32::new();
    c.update(&seq.to_le_bytes());
    c.update(&(targets.len() as u32).to_le_bytes());
    for t in targets {
        c.update(&t.to_le_bytes());
    }
    for d in datas {
        c.update(&d[..]);
    }
    c.finish()
}

pub fn commit<D: BlockDev>(
    dev: &mut D,
    sb: &Superblock,
    dirty: &BTreeMap<u32, Box<Block>>,
    seq: u64,
    bug: Bug,
) -> io::Result<()> {
    let js = sb.journal_start;
    let targets: Vec<u32> = dirty.keys().copied().collect();
    let datas: Vec<&Block> = dirty.values().map(|b| &**b).collect();
    let n = targets.len();
    assert!(n >= 1 && n <= max_tx_blocks(sb));
    let crc = tx_crc(seq, &targets, &datas);

    let mut desc = ZERO;
    desc[0..8].copy_from_slice(JDESC_MAGIC);
    put_u64(&mut desc, 8, seq);
    put_u32(&mut desc, 16, n as u32);
    put_u32(&mut desc, 20, crc);
    for (i, t) in targets.iter().enumerate() {
        put_u32(&mut desc, 24 + i * 4, *t);
    }
    let mut com = ZERO;
    com[0..8].copy_from_slice(JCOMMIT_MAGIC);
    put_u64(&mut com, 8, seq);
    put_u32(&mut com, 16, crc);

    // 1-2: journal write + barrier
    dev.write(js, &desc)?;
    for (i, d) in datas.iter().enumerate() {
        dev.write(js + 1 + i as u32, d)?;
    }
    dev.write(js + 1 + n as u32, &com)?;
    if bug != Bug::NoJournalFlush {
        dev.flush()?;
    }
    // 5 (early): the buggy variant retires the transaction before the checkpoint is safe
    if bug == Bug::EarlyClear {
        dev.write(js, &ZERO)?;
        dev.flush()?;
    }
    // 3-4: checkpoint
    for (t, d) in targets.iter().zip(datas.iter()) {
        dev.write(*t, d)?;
    }
    if bug != Bug::EarlyClear {
        dev.flush()?;
        // 5-6: retire
        dev.write(js, &ZERO)?;
    }
    dev.flush()?;
    Ok(())
}

/// Replay a committed-but-not-retired transaction. Returns the number of blocks re-applied.
pub fn replay<D: BlockDev>(dev: &mut D, sb: &Superblock, bug: Bug) -> io::Result<Option<usize>> {
    let js = sb.journal_start;
    let mut desc = ZERO;
    dev.read(js, &mut desc)?;
    if &desc[0..8] != JDESC_MAGIC {
        return Ok(None);
    }
    let seq = get_u64(&desc, 8);
    let n = get_u32(&desc, 16) as usize;
    let crc = get_u32(&desc, 20);
    if n == 0 || n > max_tx_blocks(sb) {
        return Ok(None);
    }
    let targets: Vec<u32> = (0..n).map(|i| get_u32(&desc, 24 + i * 4)).collect();
    if targets.iter().any(|&t| t >= sb.nblocks) {
        return Ok(None);
    }
    let mut com = ZERO;
    dev.read(js + 1 + n as u32, &mut com)?;
    if &com[0..8] != JCOMMIT_MAGIC || get_u64(&com, 8) != seq {
        return Ok(None);
    }
    let mut datas: Vec<Box<Block>> = Vec::with_capacity(n);
    for i in 0..n {
        let mut b = Box::new(ZERO);
        dev.read(js + 1 + i as u32, &mut b)?;
        datas.push(b);
    }
    if bug != Bug::NoCrc {
        let refs: Vec<&Block> = datas.iter().map(|b| &**b).collect();
        if tx_crc(seq, &targets, &refs) != crc || get_u32(&com, 16) != crc {
            return Ok(None);
        }
    }
    for (t, d) in targets.iter().zip(datas.iter()) {
        dev.write(*t, d)?;
    }
    dev.flush()?;
    dev.write(js, &ZERO)?;
    dev.flush()?;
    Ok(Some(n))
}

/// Inspect the journal without modifying anything: (seq, nblocks, committed?)
pub fn peek<D: BlockDev>(dev: &mut D, sb: &Superblock) -> io::Result<Option<(u64, usize, bool)>> {
    let js = sb.journal_start;
    let mut desc = ZERO;
    dev.read(js, &mut desc)?;
    if &desc[0..8] != JDESC_MAGIC {
        return Ok(None);
    }
    let seq = get_u64(&desc, 8);
    let n = get_u32(&desc, 16) as usize;
    if n == 0 || n > max_tx_blocks(sb) {
        return Ok(Some((seq, n, false)));
    }
    let mut com = ZERO;
    dev.read(js + 1 + n as u32, &mut com)?;
    Ok(Some((seq, n, &com[0..8] == JCOMMIT_MAGIC && get_u64(&com, 8) == seq)))
}
