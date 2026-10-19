use cathode::input::parse_script;
use cathode::pty::SpawnOpts;
use cathode::session::Session;

fn spawn(cmd: &[&str], cols: usize, rows: usize) -> Session {
    let argv: Vec<String> = cmd.iter().map(|s| s.to_string()).collect();
    Session::spawn(&argv, &SpawnOpts { cols, rows, ..Default::default() }, false).expect("spawn")
}

#[test]
fn runs_a_shell_command_and_captures_screen() {
    let mut s = spawn(&["sh", "-c", "printf 'hello\\nworld\\n'; exit 3"], 40, 5);
    s.pump_until_idle(300, 5000).unwrap();
    let st = s.finish(1000).expect("exited");
    assert_eq!(st.code(), Some(3));
    assert_eq!(s.term.screen.row_text(0), "hello");
    assert_eq!(s.term.screen.row_text(1), "world");
}

#[test]
fn child_sees_a_real_tty_with_our_size() {
    let mut s = spawn(&["sh", "-c", "test -t 0 && test -t 1 && echo tty; stty size; echo $TERM"], 97, 31);
    s.pump_until_idle(300, 5000).unwrap();
    s.finish(1000);
    let t = s.term.screen.text();
    assert!(t.contains("tty"), "{}", t);
    assert!(t.contains("31 97"), "{}", t);
    assert!(t.contains("xterm-256color"), "{}", t);
}

#[test]
fn onlcr_translates_newlines_so_output_is_not_staircased() {
    let mut s = spawn(&["sh", "-c", "printf 'a\\nb\\nc'"], 20, 4);
    s.pump_until_idle(300, 5000).unwrap();
    s.finish(500);
    assert_eq!((s.term.screen.row_text(0), s.term.screen.row_text(1), s.term.screen.row_text(2)), ("a".into(), "b".into(), "c".into()));
}

#[test]
fn terminal_replies_reach_the_child() {
    // The child asks for a cursor position report and echoes what the terminal answered.
    let script = r#"stty raw -echo; printf '\033[5;9H\033[6n'; dd bs=1 count=6 2>/dev/null | od -An -c; stty sane"#;
    let mut s = spawn(&["sh", "-c", script], 60, 10);
    s.pump_until_idle(500, 8000).unwrap();
    s.finish(1000);
    let t = s.term.screen.text();
    let flat: String = t.split_whitespace().collect::<Vec<_>>().join("");
    assert!(flat.contains("033[5;9R"), "{}", t);
}

#[test]
fn da1_roundtrip() {
    let script = r#"stty raw -echo; printf '\033[c'; dd bs=1 count=8 2>/dev/null | od -An -c; stty sane"#;
    let mut s = spawn(&["sh", "-c", script], 60, 10);
    s.pump_until_idle(500, 8000).unwrap();
    s.finish(1000);
    let t = s.term.screen.text();
    let flat: String = t.split_whitespace().collect::<Vec<_>>().join("");
    assert!(flat.contains("033[?62;22"), "{}", t);
}

#[test]
fn resize_delivers_sigwinch_and_new_size() {
    let script = r#"trap 'stty size; exit 0' WINCH; echo ready; while :; do sleep 0.05; done"#;
    let mut s = spawn(&["sh", "-c", script], 50, 10);
    assert!(s.wait_for_text("ready", 5000).unwrap());
    s.resize(70, 12).unwrap();
    assert!(s.wait_for_text("12 70", 5000).unwrap(), "{}", s.term.screen.text());
    s.finish(500);
}

#[test]
fn typed_input_reaches_the_child_and_is_echoed() {
    let mut s = spawn(&["cat"], 30, 4);
    s.pump_until_idle(200, 3000).unwrap();
    s.send(b"hi there\r").unwrap();
    assert!(s.wait_for_text("hi there", 3000).unwrap());
    s.finish(100);
}

#[test]
fn utf8_roundtrip_through_pty() {
    let mut s = spawn(&["cat"], 30, 4);
    s.pump_until_idle(200, 3000).unwrap();
    s.send("日本語 é\r".as_bytes()).unwrap();
    assert!(s.wait_for_text("日本語 é", 3000).unwrap(), "{}", s.term.screen.text());
    s.finish(100);
}

#[test]
fn killing_a_runaway_child() {
    let mut s = spawn(&["sh", "-c", "while :; do :; done"], 30, 4);
    s.pump_until_idle(100, 500).unwrap();
    let st = s.finish(100);
    assert!(st.is_none() || !st.unwrap().success());
}

#[test]
fn nonexistent_command_is_a_clean_error() {
    let argv = vec!["/definitely/not/a/program".to_string()];
    assert!(Session::spawn(&argv, &SpawnOpts::default(), false).is_err());
}

#[test]
fn vim_edits_a_file_inside_the_emulator() {
    let dir = std::env::temp_dir().join(format!("cathode-vim-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let file = dir.join("out.txt");
    let mut s = spawn(&["vim", "-u", "NONE", "-N", "-n", file.to_str().unwrap()], 60, 12);
    s.pump_until_idle(300, 5000).unwrap();
    let items = parse_script("ihello from cathode<Esc>:wq<CR>").unwrap();
    s.run_script(&items, 3000, 100).unwrap();
    let st = s.finish(2000).expect("vim should have exited");
    assert!(st.success());
    assert_eq!(std::fs::read_to_string(&file).unwrap(), "hello from cathode\n");
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn vim_uses_alt_screen_and_restores_main_screen() {
    let mut s = spawn(&["sh", "-c", "echo before; vim -u NONE -N -n; echo after"], 60, 12);
    assert!(s.wait_for_text("~", 5000).unwrap());
    assert!(s.term.screen.alt_active, "vim should be on the alternate screen");
    let items = parse_script(":q<CR>").unwrap();
    s.run_script(&items, 3000, 100).unwrap();
    assert!(s.wait_for_text("after", 5000).unwrap());
    assert!(!s.term.screen.alt_active);
    let t = s.term.screen.text();
    assert!(t.contains("before") && t.contains("after"), "{}", t);
    s.finish(500);
}

#[test]
fn less_pages_with_scripted_keys() {
    let mut s = spawn(&["sh", "-c", "seq 1 100 | less"], 30, 6);
    assert!(s.wait_for_text("5", 3000).unwrap());
    let items = parse_script("<Space><until \"10\">").unwrap();
    s.run_script(&items, 3000, 100).unwrap();
    let t = s.term.screen.text();
    assert!(t.contains("\n6\n") || t.starts_with("6\n") || t.contains("10"), "{}", t);
    s.finish(100);
}

#[test]
fn nano_application_cursor_keys_and_status_bar() {
    let mut s = spawn(&["nano", "--ignorercfiles"], 70, 12);
    assert!(s.wait_for_text("GNU nano", 5000).unwrap());
    let items = parse_script("abc<Left><Left>X<C-x>").unwrap();
    s.run_script(&items, 3000, 100).unwrap();
    assert!(s.wait_for_text("Save modified buffer", 3000).unwrap(), "{}", s.term.screen.text());
    s.finish(100);
}

#[test]
fn large_paste_into_echoing_child_does_not_deadlock() {
    // cat echoes every byte back; with blocking writes both sides fill their pty buffers and stall.
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let mut s = spawn(&["sh", "-c", "stty raw -echo; cat"], 80, 24);
        s.pump_until_idle(200, 2000).unwrap();
        let payload: Vec<u8> = std::iter::repeat(b"0123456789abcdef ".iter().copied()).take(20000).flatten().collect();
        let r = s.send(&payload);
        tx.send(r.is_ok()).ok();
        s.finish(100);
    });
    match rx.recv_timeout(std::time::Duration::from_secs(20)) {
        Ok(ok) => assert!(ok),
        Err(_) => panic!("send() deadlocked on a large paste"),
    }
}
