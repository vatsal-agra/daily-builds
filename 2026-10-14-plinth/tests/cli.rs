use std::process::{Command, Output};

fn plinth(args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_plinth")).args(args).env("PLINTH_NOSYNC", "1").output().unwrap()
}
fn ok(args: &[&str]) -> String {
    let o = plinth(args);
    assert!(o.status.success(), "{args:?} failed: {}{}", String::from_utf8_lossy(&o.stdout), String::from_utf8_lossy(&o.stderr));
    String::from_utf8_lossy(&o.stdout).into_owned()
}
fn err(args: &[&str]) -> String {
    let o = plinth(args);
    assert!(!o.status.success(), "{args:?} unexpectedly succeeded");
    format!("{}{}", String::from_utf8_lossy(&o.stdout), String::from_utf8_lossy(&o.stderr))
}

fn tmp(name: &str) -> String {
    let d = std::env::temp_dir().join(format!("plinth-cli-{}-{}", std::process::id(), name));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d.to_string_lossy().into_owned()
}

#[test]
fn cli_end_to_end() {
    let d = tmp("e2e");
    let img = format!("{d}/x.img");
    ok(&["mkfs", &img, "--blocks", "2048", "--inodes", "64"]);
    ok(&["mkdir", &img, "/a"]);
    std::fs::write(format!("{d}/in.bin"), (0..70_000u32).map(|i| (i % 253) as u8).collect::<Vec<_>>()).unwrap();
    ok(&["put", &img, &format!("{d}/in.bin"), "/a/in.bin"]);
    ok(&["get", &img, "/a/in.bin", &format!("{d}/out.bin")]);
    assert_eq!(std::fs::read(format!("{d}/in.bin")).unwrap(), std::fs::read(format!("{d}/out.bin")).unwrap());
    ok(&["ln", &img, "/a/in.bin", "/hard"]);
    ok(&["ln-s", &img, "a/in.bin", "/soft"]);
    ok(&["mv", &img, "/a", "/b"]);
    assert!(ok(&["tree", &img]).contains("soft -> a/in.bin"));
    assert!(ok(&["ls", &img, "/"]).contains("hard"));
    assert!(ok(&["stat", &img, "/hard"]).contains("links  2"));
    ok(&["truncate", &img, "/hard", "10"]);
    assert_eq!(ok(&["cat", &img, "/hard"]).len(), 10);
    ok(&["rm", &img, "/hard"]);
    assert!(ok(&["df", &img]).contains("journal"));
    assert!(ok(&["journal", &img]).contains("empty"));
    assert!(ok(&["fsck", &img]).contains("clean"));
    // damage → detect → repair → clean
    ok(&["corrupt", &img, "7", "--seed", "1"]);
    assert!(!plinth(&["fsck", &img]).status.success());
    assert!(ok(&["fsck", &img, "--repair"]).contains("repaired"));
    assert!(ok(&["fsck", &img]).contains("clean"));
    // html map
    ok(&["map", &img, &format!("{d}/map.html")]);
    let html = std::fs::read_to_string(format!("{d}/map.html")).unwrap();
    assert!(html.contains("\"files\":[") && html.contains("/b/in.bin"));
}

#[test]
fn cli_errors_are_clear_and_nonzero() {
    let d = tmp("err");
    let img = format!("{d}/x.img");
    assert!(err(&["cat", &format!("{d}/missing.img"), "/x"]).contains("missing.img"));
    std::fs::write(&img, vec![0u8; 8192]).unwrap();
    assert!(err(&["ls", &img]).contains("not a plinth image"));
    ok(&["mkfs", &img, "--blocks", "512", "--inodes", "32"]);
    assert!(err(&["cat", &img, "/nope"]).contains("no such file"));
    assert!(err(&["mkdir", &img, "relative"]).contains("absolute"));
    ok(&["mkdir", &img, "/a"]);
    assert!(err(&["mkdir", &img, "/a"]).contains("exists"));
    assert!(err(&["rmdir", &img, "/"]).contains("invalid"));
    assert!(err(&["mkfs", &img, "--blocks", "abc"]).contains("not a valid number"));
    assert!(err(&["mkfs", &img, "--blocks", "512", "--size-mb", "1"]).contains("either"));
    assert!(err(&["mkfs", &img, "--blocks", "4", "--inodes", "32"]).contains("too small"));
    assert!(err(&["crashtest", "--bug", "bogus"]).contains("unknown bug"));
    assert!(err(&["frobnicate"]).contains("unknown command"));
    assert!(err(&["put", &img, &format!("{d}/nonexistent"), "/x"]).contains("nonexistent"));
    assert!(err(&["corrupt", &img, "99"]).contains("0-15"));
    // a file that is not an image at all
    let junk = format!("{d}/junk");
    std::fs::write(&junk, b"hello world, definitely not a filesystem. ".repeat(100)).unwrap();
    assert!(!plinth(&["fsck", &junk]).status.success());
}

#[test]
fn cli_crashtest_and_difftest() {
    assert!(ok(&["crashtest", "--seed", "5", "--ops", "15", "--variants", "2"]).contains("every recovered state passed"));
    assert!(ok(&["crashtest", "--seed", "1", "--ops", "30", "--bug", "no-crc"]).contains("killed"));
    assert!(ok(&["difftest", "--seed", "9", "--ops", "300"]).contains("agree"));
    assert!(ok(&["bugs"]).contains("replay-no-flush"));
}
