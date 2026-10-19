use cathode::input::*;
use cathode::pty::SpawnOpts;
use cathode::screen::{Modes, MouseEnc, MouseMode};
use cathode::session::Session;
use cathode::term::Term;

fn key(modes: &Modes, k: Key, m: u8) -> String {
    encode_key(modes, &k, m).iter().map(|&b| b as char).collect()
}

#[test]
fn plain_and_control_keys() {
    let m = Modes::default();
    assert_eq!(key(&m, Key::Char('a'), 0), "a");
    assert_eq!(key(&m, Key::Char('é'), 0).as_bytes(), "é".as_bytes().iter().map(|&b| b as char).collect::<String>().as_bytes());
    assert_eq!(key(&m, Key::Char('a'), CTRL), "\x01");
    assert_eq!(key(&m, Key::Char('['), CTRL), "\x1b");
    assert_eq!(key(&m, Key::Char(' '), CTRL), "\0");
    assert_eq!(key(&m, Key::Char('x'), ALT), "\x1bx");
    assert_eq!(key(&m, Key::Char('x'), CTRL | ALT), "\x1b\x18");
    assert_eq!(key(&m, Key::Enter, 0), "\r");
    assert_eq!(key(&m, Key::Tab, 0), "\t");
    assert_eq!(key(&m, Key::Tab, SHIFT), "\x1b[Z");
    assert_eq!(key(&m, Key::Backspace, 0), "\x7f");
    assert_eq!(key(&m, Key::Esc, 0), "\x1b");
}

#[test]
fn cursor_keys_follow_application_mode_and_modifiers() {
    let mut m = Modes::default();
    assert_eq!(key(&m, Key::Up, 0), "\x1b[A");
    assert_eq!(key(&m, Key::Home, 0), "\x1b[H");
    m.app_cursor = true;
    assert_eq!(key(&m, Key::Up, 0), "\x1bOA");
    assert_eq!(key(&m, Key::End, 0), "\x1bOF");
    assert_eq!(key(&m, Key::Up, CTRL), "\x1b[1;5A", "modified keys always use CSI");
    assert_eq!(key(&m, Key::Right, SHIFT | ALT), "\x1b[1;4C");
    assert_eq!(key(&m, Key::Delete, 0), "\x1b[3~");
    assert_eq!(key(&m, Key::PageDown, CTRL), "\x1b[6;5~");
}

#[test]
fn function_keys() {
    let m = Modes::default();
    assert_eq!(key(&m, Key::F(1), 0), "\x1bOP");
    assert_eq!(key(&m, Key::F(4), 0), "\x1bOS");
    assert_eq!(key(&m, Key::F(5), 0), "\x1b[15~");
    assert_eq!(key(&m, Key::F(12), 0), "\x1b[24~");
    assert_eq!(key(&m, Key::F(1), CTRL), "\x1b[1;5P");
    assert_eq!(key(&m, Key::F(9), SHIFT), "\x1b[20;2~");
}

#[test]
fn script_parsing() {
    use Item::*;
    assert_eq!(parse_script("ab<Esc>:q<CR>").unwrap(), vec![Text("ab".into()), Key(cathode::input::Key::Esc, 0), Text(":q".into()), Key(cathode::input::Key::Enter, 0)]);
    assert_eq!(parse_script("<C-S-Up><M-b><lt>").unwrap(), vec![Key(cathode::input::Key::Up, CTRL | SHIFT), Key(cathode::input::Key::Char('b'), ALT), Key(cathode::input::Key::Char('<'), 0)]);
    assert_eq!(parse_script("<wait 250><until \"a \\\"b\\\"\"><resize 90x30>").unwrap(), vec![Wait(250), Until("a \"b\"".into()), Resize(90, 30)]);
    assert_eq!(parse_script("<paste \"x\\ny\">").unwrap(), vec![Paste("x\ny".into())]);
    assert_eq!(parse_script("<focus in><focus out>").unwrap(), vec![Focus(true), Focus(false)]);
    assert!(parse_script("<wait soon>").is_err());
    assert!(parse_script("<resize 0x5>").is_err());
    assert!(parse_script("<mouse press left x,y>").is_err());
    assert!(parse_script("<F13>").is_err());
}

fn mouse_modes(mode: MouseMode, enc: MouseEnc) -> Modes {
    Modes { mouse: mode, mouse_enc: enc, ..Modes::default() }
}
fn me(kind: MouseKind, button: MouseButton, x: usize, y: usize) -> MouseEvent {
    MouseEvent { kind, button, x, y, mods: 0 }
}
fn s(b: Option<Vec<u8>>) -> String {
    b.map(|v| v.iter().map(|&c| c as char).collect()).unwrap_or_else(|| "<none>".into())
}

#[test]
fn mouse_reporting_modes_gate_events() {
    let press = me(MouseKind::Press, MouseButton::Left, 4, 2);
    let release = me(MouseKind::Release, MouseButton::Left, 4, 2);
    let drag = me(MouseKind::Move, MouseButton::Left, 5, 2);
    let hover = me(MouseKind::Move, MouseButton::None, 6, 2);
    let wheel = me(MouseKind::Press, MouseButton::WheelUp, 4, 2);
    let none = mouse_modes(MouseMode::None, MouseEnc::Sgr);
    assert!(encode_mouse(&none, &press).is_none());
    let x10 = mouse_modes(MouseMode::X10, MouseEnc::Default);
    assert!(encode_mouse(&x10, &press).is_some());
    assert!(encode_mouse(&x10, &release).is_none() && encode_mouse(&x10, &wheel).is_none());
    let normal = mouse_modes(MouseMode::Normal, MouseEnc::Sgr);
    assert!(encode_mouse(&normal, &press).is_some() && encode_mouse(&normal, &release).is_some() && encode_mouse(&normal, &wheel).is_some());
    assert!(encode_mouse(&normal, &drag).is_none() && encode_mouse(&normal, &hover).is_none());
    let button = mouse_modes(MouseMode::Button, MouseEnc::Sgr);
    assert!(encode_mouse(&button, &drag).is_some() && encode_mouse(&button, &hover).is_none());
    let any = mouse_modes(MouseMode::Any, MouseEnc::Sgr);
    assert!(encode_mouse(&any, &hover).is_some());
}

#[test]
fn mouse_encodings() {
    let press = me(MouseKind::Press, MouseButton::Right, 9, 19);
    let release = me(MouseKind::Release, MouseButton::Right, 9, 19);
    // SGR: 1-based, release keeps the button and ends in 'm'
    let sgr = mouse_modes(MouseMode::Normal, MouseEnc::Sgr);
    assert_eq!(s(encode_mouse(&sgr, &press)), "\x1b[<2;10;20M");
    assert_eq!(s(encode_mouse(&sgr, &release)), "\x1b[<2;10;20m");
    // legacy: release is button 3, coordinates offset by 32
    let def = mouse_modes(MouseMode::Normal, MouseEnc::Default);
    assert_eq!(encode_mouse(&def, &press).unwrap(), vec![0x1b, b'[', b'M', 32 + 2, 32 + 10, 32 + 20]);
    assert_eq!(encode_mouse(&def, &release).unwrap(), vec![0x1b, b'[', b'M', 32 + 3, 32 + 10, 32 + 20]);
    // legacy encoding cannot express columns beyond 223
    assert!(encode_mouse(&def, &me(MouseKind::Press, MouseButton::Left, 300, 1)).is_none());
    assert!(encode_mouse(&sgr, &me(MouseKind::Press, MouseButton::Left, 300, 1)).is_some());
    let utf8 = mouse_modes(MouseMode::Normal, MouseEnc::Utf8);
    let b = encode_mouse(&utf8, &me(MouseKind::Press, MouseButton::Left, 300, 1)).unwrap();
    assert_eq!(String::from_utf8(b[3..].to_vec()).unwrap(), format!("{}{}{}", 32 as char, char::from_u32(301 + 32).unwrap(), char::from_u32(2 + 32).unwrap()));
    let urxvt = mouse_modes(MouseMode::Normal, MouseEnc::Urxvt);
    assert_eq!(s(encode_mouse(&urxvt, &press)), "\x1b[34;10;20M");
}

#[test]
fn mouse_modifiers_motion_and_wheel_bits() {
    let any = mouse_modes(MouseMode::Any, MouseEnc::Sgr);
    let mut e = me(MouseKind::Press, MouseButton::Left, 0, 0);
    e.mods = SHIFT | ALT | CTRL;
    assert_eq!(s(encode_mouse(&any, &e)), "\x1b[<28;1;1M"); // 0 + 4 + 8 + 16
    assert_eq!(s(encode_mouse(&any, &me(MouseKind::Move, MouseButton::None, 2, 3))), "\x1b[<35;3;4M");
    assert_eq!(s(encode_mouse(&any, &me(MouseKind::Move, MouseButton::Left, 2, 3))), "\x1b[<32;3;4M");
    assert_eq!(s(encode_mouse(&any, &me(MouseKind::Press, MouseButton::WheelDown, 0, 0))), "\x1b[<65;1;1M");
}

#[test]
fn modes_are_driven_by_the_program_via_decset() {
    let mut t = Term::new(80, 24);
    t.feed(b"\x1b[?1000h\x1b[?1006h");
    assert_eq!(t.screen.modes.mouse, MouseMode::Normal);
    assert_eq!(t.screen.modes.mouse_enc, MouseEnc::Sgr);
    t.feed(b"\x1b[?1003h");
    assert_eq!(t.screen.modes.mouse, MouseMode::Any);
    t.feed(b"\x1b[?1003l\x1b[?1006l");
    assert_eq!(t.screen.modes.mouse, MouseMode::None);
    assert_eq!(t.screen.modes.mouse_enc, MouseEnc::Default);
}

#[test]
fn bracketed_paste_wraps_and_sanitises() {
    let mut m = Modes::default();
    assert_eq!(s(Some(encode_paste(&m, "a\nb\r\nc"))), "a\rb\rc", "without 2004 newlines become CR");
    m.bracketed_paste = true;
    assert_eq!(s(Some(encode_paste(&m, "hi\nthere"))), "\x1b[200~hi\nthere\x1b[201~");
    let evil = encode_paste(&m, "x\x1b[201~rm -rf ~\x1b[2\x1b[201~01~");
    let txt = s(Some(evil));
    assert_eq!(txt.matches("\x1b[201~").count(), 1, "only our own terminator may appear: {:?}", txt);
}

#[test]
fn focus_reports_only_when_enabled() {
    let mut m = Modes::default();
    assert!(encode_focus(&m, true).is_none());
    m.focus_events = true;
    assert_eq!(s(encode_focus(&m, true)), "\x1b[I");
    assert_eq!(s(encode_focus(&m, false)), "\x1b[O");
}

fn spawn(cmd: &[&str], cols: usize, rows: usize) -> Session {
    let argv: Vec<String> = cmd.iter().map(|s| s.to_string()).collect();
    Session::spawn(&argv, &SpawnOpts { cols, rows, ..Default::default() }, false).expect("spawn")
}

#[test]
fn real_vim_receives_mouse_clicks_and_bracketed_paste() {
    let dir = std::env::temp_dir().join(format!("cathode-mouse-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let f = dir.join("m.txt");
    std::fs::write(&f, "hello world\nsecond line here\nthird\n").unwrap();
    let mut sess = spawn(&["vim", "-u", "NONE", "-N", "-n", "-c", "set mouse=a ttymouse=sgr ruler", f.to_str().unwrap()], 60, 10);
    assert!(sess.wait_for_text("hello world", 5000).unwrap());
    sess.pump_until_idle(300, 2000).unwrap();
    // vim must have turned mouse reporting on through DECSET
    assert!(sess.term.screen.modes.mouse != MouseMode::None, "vim did not enable mouse reporting");
    // click on the 'l' of "line" in row 1 (0-based), column 7
    sess.run_script(&parse_script("<mouse press left 7,1><mouse release left 7,1>").unwrap(), 3000, 150).unwrap();
    assert!(sess.wait_for_text("2,8", 3000).unwrap(), "ruler should show line 2, col 8:\n{}", sess.term.screen.text());
    // bracketed paste into insert mode
    assert!(sess.term.screen.modes.bracketed_paste, "vim should have enabled bracketed paste (DECSET 2004)");
    sess.run_script(&parse_script("i<paste \"PASTED\">").unwrap(), 3000, 150).unwrap();
    assert!(sess.wait_for_text("PASTED", 3000).unwrap(), "{}", sess.term.screen.text());
    sess.finish(200);
    let _ = std::fs::remove_dir_all(&dir);
}
