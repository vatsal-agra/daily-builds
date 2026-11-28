use std::io::{Read, Write};
use sux::fm::FmIndex;
use sux::util::{Error, Result};

const USAGE: &str = "sux — succinct data structures toolkit

USAGE:
  sux index  <file|-> -o <index.sux> [--sample N] [-z]   build a full-text index (default sample 32; -z = RRR-compressed BWT)
  sux grep   <index.sux> <pattern> [-c] [-n MAX]    lines containing pattern (answered from the index alone)
  sux count  <index.sux> <pattern>                  number of occurrences
  sux locate <index.sux> <pattern> [-n MAX]         byte offsets of occurrences
  sux extract <index.sux> <start> <end>             bytes [start, end) of the original text
  sux line   <index.sux> <number>                   a single line (1-based)
  sux info   <index.sux>                            sizes and parameters
";

fn die(msg: impl std::fmt::Display) -> ! {
    eprintln!("sux: {msg}");
    std::process::exit(1);
}

fn load(path: &str) -> Result<FmIndex> {
    let data = std::fs::read(path).map_err(|e| Error::Io(format!("{path}: {e}")))?;
    FmIndex::load_bytes(&data).map_err(|e| match e {
        Error::Corrupt(m) => Error::Corrupt(format!("{path}: {m}")),
        o => o,
    })
}

/// Pull `--flag value` out of args.
fn take_opt(args: &mut Vec<String>, names: &[&str]) -> Result<Option<String>> {
    if let Some(i) = args.iter().position(|a| names.contains(&a.as_str())) {
        if i + 1 >= args.len() {
            return Err(Error::Invalid(format!("{} needs a value", args[i])));
        }
        let v = args.remove(i + 1);
        args.remove(i);
        return Ok(Some(v));
    }
    Ok(None)
}
fn take_flag(args: &mut Vec<String>, name: &str) -> bool {
    if let Some(i) = args.iter().position(|a| a == name) {
        args.remove(i);
        true
    } else {
        false
    }
}
fn num(s: &str, what: &str) -> Result<usize> {
    s.parse::<usize>().map_err(|_| Error::Invalid(format!("{what} must be a non-negative integer, got '{s}'")))
}
fn human(bytes: usize) -> String {
    if bytes >= 1 << 20 {
        format!("{:.2} MiB", bytes as f64 / (1 << 20) as f64)
    } else if bytes >= 1 << 10 {
        format!("{:.1} KiB", bytes as f64 / 1024.0)
    } else {
        format!("{bytes} B")
    }
}

fn run(mut args: Vec<String>) -> Result<()> {
    if args.is_empty() || args[0] == "-h" || args[0] == "--help" || args[0] == "help" {
        print!("{USAGE}");
        return Ok(());
    }
    let cmd = args.remove(0);
    let out = std::io::stdout();
    let mut out = std::io::BufWriter::new(out.lock());
    match cmd.as_str() {
        "index" => {
            let output = take_opt(&mut args, &["-o", "--output"])?.ok_or_else(|| Error::Invalid("index needs -o <index.sux>".into()))?;
            let compressed = take_flag(&mut args, "-z");
            let sample = take_opt(&mut args, &["--sample"])?.map(|s| num(&s, "--sample")).transpose()?.unwrap_or(32);
            let [input] = args.as_slice() else { return Err(Error::Invalid("index takes exactly one input (file or -)".into())) };
            let mut text = Vec::new();
            if input == "-" {
                std::io::stdin().read_to_end(&mut text)?;
            } else {
                text = std::fs::read(input).map_err(|e| Error::Io(format!("{input}: {e}")))?;
            }
            let t0 = std::time::Instant::now();
            let fm = FmIndex::build_with(&text, sample, compressed)?;
            let bytes = fm.save_bytes();
            std::fs::write(&output, &bytes).map_err(|e| Error::Io(format!("{output}: {e}")))?;
            writeln!(
                out,
                "indexed {} ({} lines) -> {} : {} ({:.0}% of original) in {:.2?}",
                human(text.len()),
                fm.line_count(),
                output,
                human(bytes.len()),
                if text.is_empty() { 0.0 } else { 100.0 * bytes.len() as f64 / text.len() as f64 },
                t0.elapsed()
            )?;
        }
        "grep" => {
            let count_only = take_flag(&mut args, "-c");
            let max = take_opt(&mut args, &["-n"])?.map(|s| num(&s, "-n")).transpose()?;
            let [idx, pat] = args.as_slice() else { return Err(Error::Invalid("grep <index.sux> <pattern>".into())) };
            let fm = load(idx)?;
            let hits = fm.grep(pat.as_bytes())?;
            if count_only {
                writeln!(out, "{}", hits.len())?;
            } else {
                for h in hits.iter().take(max.unwrap_or(usize::MAX)) {
                    writeln!(out, "{}:{}", h.line, String::from_utf8_lossy(&h.text))?;
                }
                if let Some(m) = max {
                    if hits.len() > m {
                        writeln!(out, "… {} more matching lines", hits.len() - m)?;
                    }
                }
            }
            if hits.is_empty() {
                out.flush()?;
                std::process::exit(1); // grep convention: no match
            }
        }
        "count" => {
            let [idx, pat] = args.as_slice() else { return Err(Error::Invalid("count <index.sux> <pattern>".into())) };
            if pat.is_empty() {
                return Err(Error::Invalid("empty pattern".into()));
            }
            writeln!(out, "{}", load(idx)?.count(pat.as_bytes()))?;
        }
        "locate" => {
            let max = take_opt(&mut args, &["-n"])?.map(|s| num(&s, "-n")).transpose()?;
            let [idx, pat] = args.as_slice() else { return Err(Error::Invalid("locate <index.sux> <pattern>".into())) };
            let pos = load(idx)?.locate(pat.as_bytes())?;
            for p in pos.iter().take(max.unwrap_or(usize::MAX)) {
                writeln!(out, "{p}")?;
            }
            if let Some(m) = max {
                if pos.len() > m {
                    writeln!(out, "… {} more", pos.len() - m)?;
                }
            }
        }
        "extract" => {
            let [idx, a, b] = args.as_slice() else { return Err(Error::Invalid("extract <index.sux> <start> <end>".into())) };
            let bytes = load(idx)?.extract(num(a, "start")?, num(b, "end")?)?;
            out.write_all(&bytes)?;
            writeln!(out)?;
        }
        "line" => {
            let [idx, n] = args.as_slice() else { return Err(Error::Invalid("line <index.sux> <number>".into())) };
            out.write_all(&load(idx)?.line(num(n, "line number")?)?)?;
            writeln!(out)?;
        }
        "info" => {
            let [idx] = args.as_slice() else { return Err(Error::Invalid("info <index.sux>".into())) };
            let fm = load(idx)?;
            let disk = std::fs::metadata(idx)?.len() as usize;
            writeln!(out, "text length      : {} bytes", fm.len())?;
            writeln!(out, "lines            : {}", fm.line_count())?;
            writeln!(out, "sample rate      : {}", fm.sample_rate())?;
            writeln!(out, "BWT levels       : {}", if fm.is_compressed() { "RRR-compressed" } else { "plain" })?;
            writeln!(out, "on disk          : {} ({:.1}% of text)", human(disk), 100.0 * disk as f64 / fm.len().max(1) as f64)?;
            writeln!(out, "in memory (bits) : {:.2} bits/char", fm.total_bits() as f64 / fm.len().max(1) as f64)?;
        }
        other => return Err(Error::Invalid(format!("unknown command '{other}' (try `sux help`)"))),
    }
    out.flush()?;
    Ok(())
}

fn main() {
    // A closed pipe (e.g. `| head`) is not an error worth a message.
    if let Err(e) = run(std::env::args().skip(1).collect()) {
        if let Error::Io(m) = &e {
            if m.contains("Broken pipe") {
                std::process::exit(0);
            }
        }
        die(e);
    }
}
