use plinth::dev::{BlockDev, FileDev, MemDev};
use plinth::error::FsError;
use plinth::fs::{Fs, MkfsOpts};
use plinth::fsck;
use plinth::fuzz::{crash_fuzz, diff_fuzz, CrashOpts, GenCfg};
use plinth::journal::{self, Bug};
use plinth::layout::*;
use plinth::repair;
use plinth::rng::Rng;
use std::process::exit;

const USAGE: &str = "plinth — a journaling filesystem and crash-consistency lab

USAGE: plinth <command> [args]

 image management
  mkfs <img> [--blocks N | --size-mb N] [--inodes N] [--journal N]   create a filesystem image
  df <img>                      space, inodes and journal geometry
  journal <img>                 show the journal state without replaying it
  fsck <img> [--repair]         check (and optionally repair) an image; replays the journal first
  map <img> <out.html>          render a block-ownership map (self-contained HTML)

 files (all paths absolute inside the image)
  ls <img> [path]    tree <img> [path]    cat <img> <path>    stat <img> <path>
  put <img> <hostfile> <path>   get <img> <path> <hostfile>
  mkdir <img> <path>    rm <img> <path>    rmdir <img> <path>    mv <img> <from> <to>
  ln <img> <existing> <new>     ln-s <img> <target> <path>       truncate <img> <path> <size>

 verification
  crashtest [--seed N] [--ops N] [--variants N] [--bug NAME] [--no-nested]
        crash a random workload at every device event, recover, fsck, compare with the model
  difftest [--seed N] [--ops N]  differential fuzz of the filesystem against the in-memory model
  corrupt <img> <kind 0-15> [--seed N]   damage an image on purpose (to try `fsck --repair`)
  bugs                           list the journal mutants crashtest can enable

Set PLINTH_NOSYNC=1 to skip fsync (fast, unsafe; for demos).";

fn die(msg: impl std::fmt::Display) -> ! {
    eprintln!("plinth: {msg}");
    exit(1);
}

fn flag(args: &mut Vec<String>, name: &str) -> Option<String> {
    let i = args.iter().position(|a| a == name)?;
    if i + 1 >= args.len() {
        die(format!("{name} needs a value"));
    }
    let v = args.remove(i + 1);
    args.remove(i);
    Some(v)
}
fn switch(args: &mut Vec<String>, name: &str) -> bool {
    match args.iter().position(|a| a == name) {
        Some(i) => {
            args.remove(i);
            true
        }
        None => false,
    }
}
fn num<T: std::str::FromStr>(s: Option<String>, name: &str, default: T) -> T {
    match s {
        None => default,
        Some(v) => v.parse().unwrap_or_else(|_| die(format!("{name}: '{v}' is not a valid number"))),
    }
}
fn need<'a>(args: &'a [String], n: usize, usage: &str) -> &'a [String] {
    if args.len() < n {
        eprintln!("plinth: usage: plinth {usage}");
        exit(2);
    }
    args
}

fn open(img: &str) -> Fs<FileDev> {
    let dev = FileDev::open(img).unwrap_or_else(|e| die(format!("{img}: {e}")));
    let fs = Fs::mount(dev).unwrap_or_else(|e| die(format!("{img}: {e}")));
    if let Some(n) = fs.replayed {
        eprintln!("plinth: replayed {n} blocks from the journal");
    }
    fs
}

fn perm_str(kind: Kind, perm: u16) -> String {
    let mut s = String::new();
    s.push(match kind {
        Kind::Dir => 'd',
        Kind::Symlink => 'l',
        Kind::File => '-',
    });
    for sh in [6, 3, 0] {
        let p = (perm >> sh) & 7;
        s.push(if p & 4 != 0 { 'r' } else { '-' });
        s.push(if p & 2 != 0 { 'w' } else { '-' });
        s.push(if p & 1 != 0 { 'x' } else { '-' });
    }
    s
}

fn fail<T>(r: Result<T, FsError>, ctx: &str) -> T {
    r.unwrap_or_else(|e| die(format!("{ctx}: {e}")))
}

fn tree<D: BlockDev>(fs: &mut Fs<D>, path: &str, prefix: &str) {
    let ents = fail(fs.readdir(path), path);
    let ents: Vec<_> = ents.into_iter().filter(|e| e.0 != "." && e.0 != "..").collect();
    for (i, (name, _, kind)) in ents.iter().enumerate() {
        let last = i + 1 == ents.len();
        let child = if path == "/" { format!("/{name}") } else { format!("{path}/{name}") };
        let extra = match kind {
            Kind::Symlink => format!(" -> {}", fs.readlink(&child).unwrap_or_default()),
            Kind::Dir => "/".to_string(),
            Kind::File => format!("  ({} B)", fs.stat(&child, false).map(|s| s.size).unwrap_or(0)),
        };
        println!("{prefix}{}{name}{extra}", if last { "└── " } else { "├── " });
        if *kind == Kind::Dir {
            tree(fs, &child, &format!("{prefix}{}", if last { "    " } else { "│   " }));
        }
    }
}

fn main() {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() || args[0] == "-h" || args[0] == "--help" || args[0] == "help" {
        println!("{USAGE}");
        return;
    }
    let cmd = args.remove(0);
    match cmd.as_str() {
        "mkfs" => {
            let blocks = flag(&mut args, "--blocks");
            let mb = flag(&mut args, "--size-mb");
            let inodes: u32 = num(flag(&mut args, "--inodes"), "--inodes", 1024);
            let journal: u32 = num(flag(&mut args, "--journal"), "--journal", 128);
            let a = need(&args, 1, "mkfs <img> [--blocks N | --size-mb N] ...");
            let nblocks: u32 = match (blocks, mb) {
                (Some(_), Some(_)) => die("give either --blocks or --size-mb"),
                (Some(b), None) => num(Some(b), "--blocks", 0),
                (None, Some(m)) => num::<u32>(Some(m), "--size-mb", 0).saturating_mul(1024),
                (None, None) => 4096,
            };
            let dev = FileDev::create(&a[0], nblocks).unwrap_or_else(|e| die(format!("{}: {e}", a[0])));
            let fs = fail(Fs::mkfs(dev, &MkfsOpts { ninodes: inodes, journal_len: journal }), "mkfs");
            let s = fs.statfs();
            println!("created {}: {} blocks ({} KiB), {} inodes, {}-block journal", a[0], s.nblocks, s.nblocks, s.ninodes, s.journal_len);
        }
        "df" => {
            let a = need(&args, 1, "df <img>");
            let fs = open(&a[0]);
            let s = fs.statfs();
            let used = s.nblocks - fs.sb.data_start - s.free_blocks;
            println!("blocks   total {:>8}   data {:>8}   used {:>8}   free {:>8}", s.nblocks, s.nblocks - fs.sb.data_start, used, s.free_blocks);
            println!("inodes   total {:>8}   free {:>8}", s.ninodes, s.free_inodes);
            println!("journal  {} blocks at {} (max {} blocks per transaction)", s.journal_len, fs.sb.journal_start, journal::max_tx_blocks(&fs.sb));
            println!("layout   inode-bitmap {}  block-bitmap {}..{}  inode-table {}..{}  data from {}", fs.sb.ibm_start, fs.sb.bbm_start, fs.sb.bbm_start + fs.sb.bbm_len - 1, fs.sb.itable_start, fs.sb.itable_start + fs.sb.itable_len - 1, fs.sb.data_start);
            println!("clock    {} committed transactions", s.clock);
        }
        "journal" => {
            let a = need(&args, 1, "journal <img>");
            let mut dev = FileDev::open(&a[0]).unwrap_or_else(|e| die(e));
            let mut b = ZERO;
            dev.read(0, &mut b).unwrap_or_else(|e| die(e));
            let sb = Superblock::decode(&b).unwrap_or_else(|e| die(e));
            match journal::peek(&mut dev, &sb).unwrap_or_else(|e| die(e)) {
                None => println!("journal is empty (no transaction awaiting replay)"),
                Some((seq, n, true)) => println!("transaction #{seq}: {n} blocks, COMMITTED — will be replayed on next mount"),
                Some((seq, n, false)) => println!("transaction #{seq}: {n} blocks, no valid commit record — will be discarded on next mount"),
            }
        }
        "fsck" => {
            let repair_mode = switch(&mut args, "--repair");
            let a = need(&args, 1, "fsck <img> [--repair]");
            let dev = FileDev::open(&a[0]).unwrap_or_else(|e| die(format!("{}: {e}", a[0])));
            if repair_mode {
                let (_, rep) = repair::repair(dev).unwrap_or_else(|e| die(format!("repair: {e}")));
                println!("{} issue(s) found", rep.before.len());
                for i in &rep.before {
                    println!("  ✗ {i}");
                }
                for ac in &rep.actions {
                    println!("  ↳ {ac}");
                }
                if rep.after.is_empty() {
                    println!("{}", if rep.before.is_empty() { "clean — nothing to do" } else { "repaired: image is now consistent" });
                } else {
                    println!("STILL BROKEN after repair:");
                    for i in &rep.after {
                        println!("  ✗ {i}");
                    }
                    exit(1);
                }
            } else {
                let fs = Fs::mount(dev).unwrap_or_else(|e| die(format!("{}: {e}", a[0])));
                if let Some(n) = fs.replayed {
                    println!("journal: replayed {n} blocks before checking");
                }
                let mut dev = fs.into_dev();
                let an = fsck::analyze(&mut dev);
                for i in &an.issues {
                    println!("✗ {i}");
                }
                if an.issues.is_empty() {
                    println!("clean: {} files, {} dirs, {} symlinks, {} data blocks in use, {} sparse hole blocks", an.stats.files, an.stats.dirs, an.stats.symlinks, an.stats.data_blocks_used, an.stats.sparse_holes);
                } else {
                    println!("{} issue(s); run with --repair", an.issues.len());
                    exit(1);
                }
            }
        }
        "map" => {
            let a = need(&args, 2, "map <img> <out.html>");
            let fs = open(&a[0]);
            let mut dev = fs.into_dev();
            let n = dev.nblocks();
            let mut img = vec![0u8; n as usize * BS];
            let mut b = ZERO;
            for i in 0..n {
                dev.read(i, &mut b).unwrap_or_else(|e| die(e));
                img[i as usize * BS..(i as usize + 1) * BS].copy_from_slice(&b);
            }
            let html = plinth::report::html_map(img, &a[0]);
            std::fs::write(&a[1], html).unwrap_or_else(|e| die(format!("{}: {e}", a[1])));
            println!("wrote {}", a[1]);
        }
        "ls" => {
            let a = need(&args, 1, "ls <img> [path]");
            let mut fs = open(&a[0]);
            let path = a.get(1).map(String::as_str).unwrap_or("/");
            let st = fail(fs.stat(path, true), path);
            if st.kind != Kind::Dir {
                println!("{} {:>3} {:>10}  {path}", perm_str(st.kind, st.perm), st.nlink, st.size);
                return;
            }
            for (name, ino, kind) in fail(fs.readdir(path), path) {
                let child = if path == "/" { format!("/{name}") } else { format!("{path}/{name}") };
                let s = fail(fs.stat_ino(ino), &name);
                let tail = if kind == Kind::Symlink && name != "." && name != ".." { format!(" -> {}", fs.readlink(&child).unwrap_or_default()) } else { String::new() };
                println!("{} {:>3} {:>10} {:>5}  {name}{tail}", perm_str(kind, s.perm), s.nlink, s.size, ino);
            }
        }
        "tree" => {
            let a = need(&args, 1, "tree <img> [path]");
            let mut fs = open(&a[0]);
            let path = a.get(1).map(String::as_str).unwrap_or("/");
            println!("{path}");
            tree(&mut fs, path, "");
        }
        "cat" => {
            let a = need(&args, 2, "cat <img> <path>");
            let mut fs = open(&a[0]);
            let data = fail(fs.read_all(&a[1]), &a[1]);
            use std::io::Write;
            std::io::stdout().write_all(&data).ok();
        }
        "stat" => {
            let a = need(&args, 2, "stat <img> <path>");
            let mut fs = open(&a[0]);
            let s = fail(fs.stat(&a[1], false), &a[1]);
            println!("  path   {}\n  inode  {}\n  type   {}\n  perm   {:o} ({})\n  links  {}\n  size   {} bytes\n  blocks {} (incl. indirect)\n  mtime  txn #{}", a[1], s.ino, s.kind.name(), s.perm, perm_str(s.kind, s.perm), s.nlink, s.size, s.blocks, s.mtime);
            if s.kind == Kind::Symlink {
                println!("  target {}", fs.readlink(&a[1]).unwrap_or_default());
            }
        }
        "put" => {
            let a = need(&args, 3, "put <img> <hostfile> <path>");
            let data = std::fs::read(&a[1]).unwrap_or_else(|e| die(format!("{}: {e}", a[1])));
            let mut fs = open(&a[0]);
            if fs.stat(&a[2], true).is_err() {
                fail(fs.create(&a[2]), &a[2]);
            }
            fail(fs.truncate(&a[2], 0), &a[2]);
            fail(fs.write(&a[2], 0, &data), &a[2]);
            println!("{} -> {} ({} bytes)", a[1], a[2], data.len());
        }
        "get" => {
            let a = need(&args, 3, "get <img> <path> <hostfile>");
            let mut fs = open(&a[0]);
            let data = fail(fs.read_all(&a[1]), &a[1]);
            std::fs::write(&a[2], &data).unwrap_or_else(|e| die(format!("{}: {e}", a[2])));
            println!("{} -> {} ({} bytes)", a[1], a[2], data.len());
        }
        "mkdir" => {
            let a = need(&args, 2, "mkdir <img> <path>");
            fail(open(&a[0]).mkdir(&a[1]), &a[1]);
        }
        "rm" => {
            let a = need(&args, 2, "rm <img> <path>");
            fail(open(&a[0]).unlink(&a[1]), &a[1]);
        }
        "rmdir" => {
            let a = need(&args, 2, "rmdir <img> <path>");
            fail(open(&a[0]).rmdir(&a[1]), &a[1]);
        }
        "mv" => {
            let a = need(&args, 3, "mv <img> <from> <to>");
            fail(open(&a[0]).rename(&a[1], &a[2]), &a[1]);
        }
        "ln" => {
            let a = need(&args, 3, "ln <img> <existing> <new>");
            fail(open(&a[0]).link(&a[1], &a[2]), &a[2]);
        }
        "ln-s" => {
            let a = need(&args, 3, "ln-s <img> <target> <path>");
            fail(open(&a[0]).symlink(&a[1], &a[2]), &a[2]);
        }
        "truncate" => {
            let a = need(&args, 3, "truncate <img> <path> <size>");
            let size: u64 = a[2].parse().unwrap_or_else(|_| die("size must be a number"));
            fail(open(&a[0]).truncate(&a[1], size), &a[1]);
        }
        "bugs" => {
            for b in Bug::ALL_MUTANTS {
                println!("{}", b.name());
            }
        }
        "difftest" => {
            let seed: u64 = num(flag(&mut args, "--seed"), "--seed", 1);
            let ops: usize = num(flag(&mut args, "--ops"), "--ops", 1000);
            let cfg = GenCfg { max_write: 40 * 1024, max_off: 400 * 1024 };
            match diff_fuzz(seed, ops, 4096, &cfg) {
                Ok(r) => println!("seed {seed}: {} ops ({} succeeded, {} rejected identically by both), {} remounts — filesystem and model agree, fsck clean", r.ops, r.ok_ops, r.failed_ops, r.remounts),
                Err(e) => {
                    println!("MISMATCH: {e}");
                    exit(1);
                }
            }
        }
        "crashtest" => {
            let mut o = CrashOpts::default();
            o.seed = num(flag(&mut args, "--seed"), "--seed", 1);
            o.ops = num(flag(&mut args, "--ops"), "--ops", 40);
            o.variants = num(flag(&mut args, "--variants"), "--variants", 4);
            o.nested = !switch(&mut args, "--no-nested");
            if let Some(b) = flag(&mut args, "--bug") {
                o.bug = Bug::parse(&b).unwrap_or_else(|| die(format!("unknown bug '{b}' (see `plinth bugs`)")));
            }
            let r = crash_fuzz(&o);
            if !r.workload_errors.is_empty() {
                println!("WORKLOAD ERROR: {}", r.workload_errors[0]);
                exit(1);
            }
            println!(
                "seed {}: {} ops → {} device events ({} writes, {} flushes)\n  explored {} crash states ({} with a torn write); {} needed journal replay; {} further states explored by crashing inside recovery itself",
                o.seed, o.ops, r.events, r.writes, r.flushes, r.states_checked, r.torn_states, r.replays, r.nested_states
            );
            if r.failures.is_empty() {
                println!("  every recovered state passed fsck and equals the state before or after the interrupted operation{}", if o.bug != Bug::None { "  (!! mutant SURVIVED)" } else { "" });
                if o.bug != Bug::None {
                    exit(1);
                }
            } else {
                println!("  {} FAILURE(S){}:", r.failures.len(), if o.bug != Bug::None { format!(" — mutant '{}' killed", o.bug.name()) } else { String::new() });
                for f in r.failures.iter().take(3) {
                    println!("   • crash before event {} ({} ops completed, {}): {}", f.event, f.ops_done, f.variant, f.what);
                }
                if o.bug == Bug::None {
                    exit(1);
                }
            }
        }
        "corrupt" => {
            let seed: u64 = num(flag(&mut args, "--seed"), "--seed", 1);
            let a = need(&args, 2, "corrupt <img> <kind 0-15> [--seed N]");
            let kind: usize = a[1].parse().unwrap_or_else(|_| die("kind must be a number 0-15"));
            if kind >= repair::CORRUPTION_KINDS {
                die("kind must be 0-15");
            }
            let mut fs = open(&a[0]);
            let mut dev = {
                let n = fs.dev.nblocks();
                let mut m = MemDev::new(n);
                let mut b = ZERO;
                for i in 0..n {
                    fs.dev.read(i, &mut b).unwrap();
                    m.write(i, &b).unwrap();
                }
                m
            };
            let mut rng = Rng::new(seed);
            match repair::inject(&mut dev.data, kind, &mut rng) {
                Some(d) => {
                    for i in 0..dev.nblocks() {
                        let mut b = ZERO;
                        dev.read(i, &mut b).unwrap();
                        fs.dev.write(i, &b).unwrap();
                    }
                    fs.dev.flush().unwrap();
                    println!("damaged: {d}");
                }
                None => die("that kind of damage is not applicable to this image (try another kind or seed)"),
            }
        }
        other => {
            eprintln!("plinth: unknown command '{other}'\n\n{USAGE}");
            exit(2);
        }
    }
}
