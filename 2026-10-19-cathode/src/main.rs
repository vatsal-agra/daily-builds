use cathode::cast::{player_html, Cast};
use cathode::input::{encode_key, parse_script, Item};
use cathode::pty::{describe_status, SpawnOpts};
use cathode::render::*;
use cathode::session::Session;
use cathode::term::Term;
use std::io::{Read, Write};
use std::process::ExitCode;

const USAGE: &str = "\
cathode — a from-scratch terminal emulator core

USAGE
  cathode run [OPTIONS] -- CMD [ARGS...]   run a program on a PTY, then print the final screen
  cathode feed [OPTIONS] [FILE|-]          feed raw bytes (an escape-sequence stream) to a terminal
  cathode replay FILE.cast [OPTIONS]       replay an asciicast v2 recording
  cathode keys SCRIPT                      show the bytes a key script would send
  cathode help | version

COMMON OPTIONS
  --cols N, --rows N      terminal size (default 80x24)
  --format FMT            text (default) | ansi | html | svg | json
  --theme T               dark | light | auto (html/svg)
  --scrollback            include scrollback above the visible screen (text/html/svg)
  --no-cursor             do not draw the cursor (html/svg)
  -o, --output FILE       write the result to FILE instead of stdout

RUN OPTIONS
  --keys SCRIPT           input script, e.g. 'ihello<Esc>:q!<CR>'. Specials: <Esc> <CR> <Tab> <BS> <Del>
                          <Up> <Down> <Left> <Right> <Home> <End> <PageUp> <PageDown> <F1>..<F12>
                          <C-x> <M-x> <S-Tab> <C-S-Up> <lt> <wait 300> <until \"text\"> <resize 100x30>
  --settle MS             quiet period that counts as 'idle' (default 250)
  --timeout MS            overall limit for the session (default 15000)
  --until-timeout MS      limit for each <until \"..\"> (default 5000)
  --record FILE           write an asciicast v2 recording
  --record-input          include keystrokes in the recording
  --env K=V               extra environment variable (repeatable)
  --cwd DIR               working directory for the child
  --exit-code             exit with the child's exit status
  --show-replies          print the terminal's query replies seen by the child to stderr (debug)

FEED OPTIONS
  --show-replies          print the replies the terminal generated (escaped) to stderr

REPLAY OPTIONS
  --at SECONDS            snapshot at a point in time (default: the end)
  --idle-limit SECONDS    compress idle gaps longer than this
  --player FILE.html      write a self-contained HTML player (with --max-frames N, default 400)
  --tty                   play back to the real terminal in real time (--speed X)
";

struct Args {
    pos: Vec<String>,
    flags: Vec<(String, Option<String>)>,
    rest: Vec<String>,
}

const VALUE_FLAGS: &[&str] = &[
    "--cols", "--rows", "--format", "--theme", "-o", "--output", "--keys", "--settle", "--timeout", "--until-timeout", "--record", "--env", "--cwd", "--at",
    "--idle-limit", "--player", "--max-frames", "--speed", "--title",
];

fn parse_args(argv: &[String]) -> Result<Args, String> {
    let mut a = Args { pos: vec![], flags: vec![], rest: vec![] };
    let mut i = 0;
    while i < argv.len() {
        let s = &argv[i];
        if s == "--" {
            a.rest = argv[i + 1..].to_vec();
            break;
        }
        if s.starts_with('-') && s.len() > 1 {
            let (name, inline) = match s.split_once('=') {
                Some((n, v)) if n.starts_with("--") => (n.to_string(), Some(v.to_string())),
                _ => (s.clone(), None),
            };
            if VALUE_FLAGS.contains(&name.as_str()) {
                let v = match inline {
                    Some(v) => v,
                    None => {
                        i += 1;
                        argv.get(i).cloned().ok_or_else(|| format!("{} needs a value", name))?
                    }
                };
                a.flags.push((name, Some(v)));
            } else if ["--scrollback", "--no-cursor", "--record-input", "--exit-code", "--show-replies", "--tty"].contains(&name.as_str()) {
                a.flags.push((name, None));
            } else {
                return Err(format!("unknown option {}", name));
            }
        } else {
            a.pos.push(s.clone());
        }
        i += 1;
    }
    Ok(a)
}

impl Args {
    fn val(&self, n: &str) -> Option<&str> {
        self.flags.iter().rev().find(|(k, _)| k == n).and_then(|(_, v)| v.as_deref())
    }
    fn has(&self, n: &str) -> bool {
        self.flags.iter().any(|(k, _)| k == n)
    }
    fn num<T: std::str::FromStr>(&self, n: &str, default: T) -> Result<T, String> {
        match self.val(n) {
            None => Ok(default),
            Some(v) => v.parse::<T>().map_err(|_| format!("{} expects a number, got {:?}", n, v)),
        }
    }
    fn size(&self) -> Result<(usize, usize), String> {
        let c: usize = self.num("--cols", 80)?;
        let r: usize = self.num("--rows", 24)?;
        if !(1..=1000).contains(&c) || !(1..=1000).contains(&r) {
            return Err("--cols and --rows must be between 1 and 1000".into());
        }
        Ok((c, r))
    }
}

fn render_opts(a: &Args) -> Result<RenderOpts, String> {
    let theme = match a.val("--theme").unwrap_or("auto") {
        "dark" => Theme::Dark,
        "light" => Theme::Light,
        "auto" => Theme::Auto,
        t => return Err(format!("unknown theme {:?} (dark|light|auto)", t)),
    };
    Ok(RenderOpts { theme, cursor: !a.has("--no-cursor"), scrollback: a.has("--scrollback"), title: a.val("--title").map(String::from) })
}

fn render(a: &Args, term: &Term) -> Result<Vec<u8>, String> {
    let opts = render_opts(a)?;
    let s = &term.screen;
    Ok(match a.val("--format").unwrap_or("text") {
        "text" => {
            let mut t = to_text(s, opts.scrollback);
            t.push('\n');
            t.into_bytes()
        }
        "ansi" => to_ansi(s),
        "html" => to_html(s, &opts).into_bytes(),
        "svg" => to_svg(s, &opts).into_bytes(),
        "json" => {
            let mut j = to_json(s).to_json();
            j.push('\n');
            j.into_bytes()
        }
        f => return Err(format!("unknown format {:?} (text|ansi|html|svg|json)", f)),
    })
}

fn emit(a: &Args, bytes: &[u8]) -> Result<(), String> {
    match a.val("-o").or(a.val("--output")) {
        Some(p) => std::fs::write(p, bytes).map_err(|e| format!("cannot write {}: {}", p, e)),
        None => std::io::stdout().write_all(bytes).map_err(|e| e.to_string()),
    }
}

fn escape_bytes(b: &[u8]) -> String {
    let mut s = String::new();
    for &c in b {
        match c {
            0x1b => s.push_str("\\e"),
            b'\r' => s.push_str("\\r"),
            b'\n' => s.push_str("\\n"),
            0x20..=0x7e => s.push(c as char),
            _ => s.push_str(&format!("\\x{:02x}", c)),
        }
    }
    s
}

fn cmd_run(a: &Args) -> Result<ExitCode, String> {
    if a.rest.is_empty() {
        return Err("run needs a command after `--`".into());
    }
    let (cols, rows) = a.size()?;
    let mut env = Vec::new();
    for (k, v) in &a.flags {
        if k == "--env" {
            let v = v.as_deref().unwrap_or("");
            let (name, val) = v.split_once('=').ok_or_else(|| format!("--env expects K=V, got {:?}", v))?;
            env.push((name.to_string(), val.to_string()));
        }
    }
    let opts = SpawnOpts { cols, rows, env, cwd: a.val("--cwd").map(String::from) };
    let settle: u64 = a.num("--settle", 250)?;
    let timeout: u64 = a.num("--timeout", 15000)?;
    let until_timeout: u64 = a.num("--until-timeout", 5000)?;
    let items: Vec<Item> = match a.val("--keys") {
        Some(k) => parse_script(k)?,
        None => vec![],
    };
    let mut sess = Session::spawn(&a.rest, &opts, a.val("--record").is_some()).map_err(|e| format!("cannot start {:?}: {}", a.rest[0], e))?;
    sess.record_input = a.has("--record-input");
    sess.pump_until_idle(settle, timeout.min(5000)).map_err(|e| e.to_string())?;
    let script_res = sess.run_script(&items, until_timeout, settle.min(120));
    let _ = sess.pump_until_idle(settle, timeout);
    let status = sess.finish(if sess.is_alive() { 100 } else { 0 });
    if let Err(e) = script_res {
        eprintln!("cathode: script failed: {}", e);
        return Ok(ExitCode::from(3));
    }
    if a.has("--show-replies") {
        eprintln!("cathode: {} bytes read from child", sess.bytes_read);
    }
    let out = render(a, &sess.term)?;
    emit(a, &out)?;
    if let (Some(path), Some(c)) = (a.val("--record"), &sess.cast) {
        std::fs::write(path, c.to_string()).map_err(|e| format!("cannot write {}: {}", path, e))?;
    }
    if let Some(st) = status {
        eprintln!("cathode: child {}", describe_status(&st));
        if a.has("--exit-code") {
            return Ok(ExitCode::from(st.code().unwrap_or(128) as u8));
        }
    } else {
        eprintln!("cathode: child still running, killed");
    }
    Ok(ExitCode::SUCCESS)
}

fn cmd_feed(a: &Args) -> Result<ExitCode, String> {
    let (cols, rows) = a.size()?;
    let mut data = Vec::new();
    match a.pos.first().map(String::as_str) {
        None | Some("-") => {
            std::io::stdin().read_to_end(&mut data).map_err(|e| e.to_string())?;
        }
        Some(p) => data = std::fs::read(p).map_err(|e| format!("cannot read {}: {}", p, e))?,
    }
    let mut t = Term::new(cols, rows);
    t.feed(&data);
    if a.has("--show-replies") {
        eprintln!("replies: {}", escape_bytes(&t.out));
    }
    let out = render(a, &t)?;
    emit(a, &out)?;
    Ok(ExitCode::SUCCESS)
}

fn cmd_replay(a: &Args) -> Result<ExitCode, String> {
    let path = a.pos.first().ok_or("replay needs a .cast file")?;
    let src = std::fs::read_to_string(path).map_err(|e| format!("cannot read {}: {}", path, e))?;
    let mut cast = Cast::parse(&src).map_err(|e| format!("{}: {}", path, e))?;
    if let Some(l) = a.val("--idle-limit") {
        let l: f64 = l.parse().map_err(|_| "--idle-limit expects seconds".to_string())?;
        if l.is_nan() || l < 0.0 {
            return Err("--idle-limit must be >= 0".into());
        }
        cast.cap_idle(l);
    }
    if let Some(p) = a.val("--player") {
        let theme = render_opts(a)?.theme;
        let html = player_html(&cast, theme, a.num("--max-frames", 400usize)?);
        std::fs::write(p, html).map_err(|e| format!("cannot write {}: {}", p, e))?;
        eprintln!("cathode: wrote player {} ({} events, {:.1}s)", p, cast.events.len(), cast.duration());
        return Ok(ExitCode::SUCCESS);
    }
    if a.has("--tty") {
        let speed: f64 = a.num("--speed", 1.0)?;
        if !(speed > 0.0) {
            return Err("--speed must be positive".into());
        }
        let mut last = 0.0;
        let mut out = std::io::stdout();
        for e in cast.events.iter().filter(|e| e.kind == 'o') {
            std::thread::sleep(std::time::Duration::from_secs_f64(((e.t - last) / speed).max(0.0)));
            last = e.t;
            out.write_all(e.data.as_bytes()).map_err(|e| e.to_string())?;
            out.flush().ok();
        }
        return Ok(ExitCode::SUCCESS);
    }
    let at = match a.val("--at") {
        Some(v) => Some(v.parse::<f64>().map_err(|_| "--at expects seconds".to_string())?),
        None => None,
    };
    let term = cast.replay(at);
    let out = render(a, &term)?;
    emit(a, &out)?;
    Ok(ExitCode::SUCCESS)
}

fn cmd_keys(a: &Args) -> Result<ExitCode, String> {
    let script = a.pos.first().ok_or("keys needs a script")?;
    let items = parse_script(script)?;
    let modes = cathode::screen::Modes::default();
    for it in items {
        match it {
            Item::Text(t) => println!("text  {}", escape_bytes(t.as_bytes())),
            Item::Key(k, m) => println!("key   {}", escape_bytes(&encode_key(&modes, &k, m))),
            other => println!("{:?}", other),
        }
    }
    Ok(ExitCode::SUCCESS)
}

fn main() -> ExitCode {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let Some(cmd) = argv.first().cloned() else {
        eprint!("{}", USAGE);
        return ExitCode::from(2);
    };
    let res = match cmd.as_str() {
        "help" | "-h" | "--help" => {
            print!("{}", USAGE);
            return ExitCode::SUCCESS;
        }
        "version" | "--version" => {
            println!("cathode {}", cathode::term::VERSION);
            return ExitCode::SUCCESS;
        }
        "run" | "feed" | "replay" | "keys" => parse_args(&argv[1..]).and_then(|a| match cmd.as_str() {
            "run" => cmd_run(&a),
            "feed" => cmd_feed(&a),
            "replay" => cmd_replay(&a),
            _ => cmd_keys(&a),
        }),
        other => Err(format!("unknown command {:?} (try `cathode help`)", other)),
    };
    match res {
        Ok(c) => c,
        Err(e) => {
            eprintln!("cathode: {}", e);
            ExitCode::from(2)
        }
    }
}
