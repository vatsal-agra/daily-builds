//! Real programs: record the bytes vim/less/nano/ls emit inside Cathode, then feed the very same
//! bytes to a real tmux pane and require identical screens.
use cathode::input::parse_script;
use cathode::pty::SpawnOpts;
use cathode::session::Session;
use cathode::tmuxdiff::{compare_with, tmux_available, Opts};

fn record(cmd: &[&str], cols: usize, rows: usize, keys: &str) -> Vec<u8> {
    let argv: Vec<String> = cmd.iter().map(|s| s.to_string()).collect();
    let mut s = Session::spawn(&argv, &SpawnOpts { cols, rows, ..Default::default() }, true).expect("spawn");
    s.pump_until_idle(400, 6000).unwrap();
    s.run_script(&parse_script(keys).unwrap(), 4000, 150).unwrap();
    s.pump_until_idle(300, 3000).unwrap();
    s.finish(300);
    let cast = s.cast.take().unwrap();
    cast.events.iter().filter(|e| e.kind == 'o').flat_map(|e| e.data.as_bytes().to_vec()).collect()
}

fn check(name: &str, stream: &[u8], cols: usize, rows: usize) {
    if !tmux_available() {
        eprintln!("SKIPPED {}: tmux not installed", name);
        return;
    }
    assert!(!stream.is_empty(), "{}: recorded nothing", name);
    // Whole-line background fills and scroll-created lines are not comparable (tmux has no BCE there).
    let rep = compare_with(stream, cols, rows, Opts { cursor: true, blank_bg: false }).unwrap_or_else(|e| panic!("{}: {}", name, e));
    assert!(rep.ok(), "{}: {} mismatches ({} cells)\n{}", name, rep.mismatches.len(), rep.cells_compared, rep.mismatches.join("\n"));
}

#[test]
fn ls_color_listing() {
    let s = record(&["sh", "-c", "ls --color=always -l /usr /bin | head -20; printf '\\033[1;4mbold underline\\033[0m done\\n'"], 100, 30, "");
    check("ls", &s, 100, 30);
}

#[test]
fn vim_with_syntax_and_editing() {
    let dir = std::env::temp_dir().join(format!("cathode-tmuxprog-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let f = dir.join("demo.py");
    std::fs::write(&f, "import os\n\ndef greet(name):\n    # say hi\n    print(\"hello, \" + name, 42)\n\nclass A:\n    pass\n").unwrap();
    let s = record(&["vim", "-u", "NONE", "-N", "-n", "-c", "syntax on | set bg=dark | set number | set ruler", f.to_str().unwrap()], 70, 20, "3Gdd/print<CR>ihello <Esc>:set cursorline<CR>");
    check("vim", &s, 70, 20);
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn less_scrolling() {
    let s = record(&["sh", "-c", "seq 1 200 | less"], 50, 12, "<Space><Space>k/9<CR>");
    check("less", &s, 50, 12);
}

#[test]
fn nano_status_bar_and_editing() {
    let s = record(&["nano", "--ignorercfiles"], 80, 16, "hello nano<CR>second line<C-g>");
    check("nano", &s, 80, 16);
}

#[test]
fn top_batch_style_screen() {
    // `top` redraws with cursor addressing and SGR; only the structure (not the numbers) must match,
    // and since both emulators see the same bytes the screens must be identical.
    let s = record(&["top"], 100, 20, "<wait 300>");
    check("top", &s, 100, 20);
}
