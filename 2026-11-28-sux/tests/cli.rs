use std::process::{Command, Output};

fn sux(args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_sux")).args(args).output().unwrap()
}
fn out(o: &Output) -> String {
    String::from_utf8_lossy(&o.stdout).to_string()
}
fn tmp(name: &str) -> String {
    let d = std::env::temp_dir().join(format!("sux-test-{}", std::process::id()));
    std::fs::create_dir_all(&d).unwrap();
    d.join(name).to_string_lossy().to_string()
}

#[test]
fn index_grep_count_locate_extract_line_info() {
    let txt = tmp("a.txt");
    let idx = tmp("a.sux");
    std::fs::write(&txt, "the quick brown fox\njumps over -c the lazy dog\nthe end\n").unwrap();
    let o = sux(&["index", &txt, "-o", &idx]);
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    assert!(out(&o).contains("3 lines"));
    assert_eq!(out(&sux(&["count", &idx, "the"])).trim(), "3");
    assert_eq!(out(&sux(&["grep", &idx, "the"])), "1:the quick brown fox\n2:jumps over -c the lazy dog\n3:the end\n");
    assert_eq!(out(&sux(&["grep", &idx, "the", "-c"])).trim(), "3");
    assert_eq!(out(&sux(&["grep", &idx, "the", "-n", "1"])), "1:the quick brown fox\n… 2 more matching lines\n");
    assert_eq!(out(&sux(&["locate", &idx, "the"])), "0\n34\n47\n");
    assert_eq!(out(&sux(&["extract", &idx, "4", "9"])), "quick\n");
    assert_eq!(out(&sux(&["line", &idx, "3"])), "the end\n");
    // `--` lets a pattern look like a flag
    assert_eq!(out(&sux(&["grep", &idx, "--", "-c"])), "2:jumps over -c the lazy dog\n");
    let info = out(&sux(&["info", &idx]));
    assert!(info.contains("text length") && info.contains("plain"));
}

#[test]
fn errors_are_clean_and_exit_nonzero() {
    let txt = tmp("b.txt");
    let idx = tmp("b.sux");
    std::fs::write(&txt, "hello\n").unwrap();
    assert!(sux(&["index", &txt, "-o", &idx]).status.success());
    let no_match = sux(&["grep", &idx, "zzz"]);
    assert_eq!(no_match.status.code(), Some(1));
    assert!(no_match.stderr.is_empty()); // grep convention: silent exit 1
    for args in [
        vec!["bogus"],
        vec!["grep", &idx],
        vec!["grep", &idx, "--nope"],
        vec!["count", &idx, ""],
        vec!["extract", &idx, "5", "2"],
        vec!["extract", &idx, "x", "2"],
        vec!["index", &txt],
        vec!["index", "/does/not/exist", "-o", &idx],
        vec!["index", &txt, "-o", &idx, "--sample", "0"],
        vec!["info", "/does/not/exist"],
    ] {
        let o = sux(&args);
        assert_eq!(o.status.code(), Some(1), "{args:?}");
        let e = String::from_utf8_lossy(&o.stderr);
        assert!(e.starts_with("sux: ") && !e.contains("panicked"), "{args:?}: {e}");
    }
    // A damaged index is reported, not trusted.
    let mut bytes = std::fs::read(&idx).unwrap();
    let mid = bytes.len() / 2;
    bytes[mid] ^= 0xFF;
    let bad = tmp("bad.sux");
    std::fs::write(&bad, &bytes).unwrap();
    let o = sux(&["count", &bad, "h"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&o.stderr).contains("checksum"));
}

#[test]
fn compressed_index_and_stdin_and_empty_file() {
    let idx = tmp("c.sux");
    let mut child = Command::new(env!("CARGO_BIN_EXE_sux"))
        .args(["index", "-", "-o", &idx, "-z", "--sample", "8"])
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .spawn()
        .unwrap();
    use std::io::Write;
    child.stdin.take().unwrap().write_all(b"aaa\nbab\n").unwrap();
    assert!(child.wait_with_output().unwrap().status.success());
    assert_eq!(out(&sux(&["count", &idx, "a"])).trim(), "4");
    assert!(out(&sux(&["info", &idx])).contains("RRR"));
    let empty = tmp("empty.txt");
    std::fs::write(&empty, "").unwrap();
    let eidx = tmp("empty.sux");
    assert!(sux(&["index", &empty, "-o", &eidx]).status.success());
    assert_eq!(sux(&["grep", &eidx, "x"]).status.code(), Some(1));
    assert_eq!(out(&sux(&["extract", &eidx, "0", "0"])), "\n");
}

#[test]
fn trie_subcommands() {
    let words = tmp("words.txt");
    let t = tmp("w.trie");
    std::fs::write(&words, "banana\nband\nbandana\r\n\ncan\nband\napple\n").unwrap();
    let o = sux(&["trie", "build", &words, "-o", &t]);
    assert!(o.status.success(), "{}", String::from_utf8_lossy(&o.stderr));
    assert!(out(&o).starts_with("5 distinct words"));
    assert_eq!(out(&sux(&["trie", "complete", &t, "ban"])), "banana\nband\nbandana\n");
    assert_eq!(out(&sux(&["trie", "complete", &t, "ban", "-n", "1"])), "banana\n… 2 more\n");
    assert_eq!(out(&sux(&["trie", "complete", &t, "zzz"])), "");
    let id = out(&sux(&["trie", "lookup", &t, "can"])).trim().to_string();
    assert_eq!(out(&sux(&["trie", "key", &t, &id])).trim(), "can");
    assert_eq!(sux(&["trie", "lookup", &t, "cat"]).status.code(), Some(1));
    assert_eq!(sux(&["trie", "key", &t, "99"]).status.code(), Some(1));
    assert_eq!(sux(&["trie", "nope"]).status.code(), Some(1));
    assert!(out(&sux(&["trie", "info", &t])).contains("words : 5"));
    // an FM index is not a trie file
    let txt = tmp("n.txt");
    let idx = tmp("n.sux");
    std::fs::write(&txt, "x\n").unwrap();
    sux(&["index", &txt, "-o", &idx]);
    let o = sux(&["trie", "info", &idx]);
    assert_eq!(o.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&o.stderr).contains("bad magic"));
}

#[test]
fn bench_command_runs() {
    let o = sux(&["bench", "--quick"]);
    assert!(o.status.success());
    assert!(out(&o).contains("EliasFano") && out(&o).contains("ns/query"));
    assert_eq!(sux(&["bench", "extra"]).status.code(), Some(1));
}
