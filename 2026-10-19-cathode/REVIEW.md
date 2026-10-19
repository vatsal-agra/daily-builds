# REVIEW — adversarial pass over Phase 2

Method: read every module as a hostile reviewer, then attack it with (a) structure-aware and
pure-random fuzzing under debug (overflow-checked) and release builds, with grid invariants checked
every few steps (`tests/fuzz.rs`), (b) real programs (vim, nano, less, top, nested tmux) through the
PTY, (c) screenshots of the HTML renderer in headless Chromium, (d) bad CLI input, (e) a throughput
benchmark (12 MB of SGR-heavy text in 0.4 s; 30 MB plain in 0.8 s — no finding).

Every finding below has a regression test (listed) and is fixed.

| ID | Severity | Finding | How found | Fix | Regression test |
|----|----------|---------|-----------|-----|-----------------|
| R-01 | **High** | **Deadlock**: `Session::send` used a blocking `write(2)` on the PTY master. Pasting >~64 KB into a raw-mode child that echoes (e.g. `stty raw -echo; cat`) fills the child's output queue *and* its input queue while we sit in `write`, so both sides wait forever. Reply writes (DSR/DA answers) had the same hazard. | Reasoned from the pty buffer model, then reproduced: test hung 20 s | Master set `O_NONBLOCK`; `send` loops `try_write` and, when the queue is full, **pumps output** (5 ms) with a 30 s overall deadline; query replies go through a bounded queue flushed opportunistically | `pty::large_paste_into_echoing_child_does_not_deadlock` |
| R-02 | **High (visual)** | HTML output was **double-spaced**: rows were joined with `"\n"` inside `<pre>`, and a newline text node between block-level row `<div>`s renders as an extra blank line. Row heights measured by script looked right (17.5 px each), so only the screenshot revealed it. | Screenshot of `ls --color` demo | Rows joined with `""` (HTML renderer and the cast player's JS) | `review_regressions::r02_html_rows_are_adjacent` + re-screenshot |
| R-03 | Medium | OSC 8 hyperlink table grew without bound: a stream of unique URLs is a memory-exhaustion vector; URIs up to 1 MB each. | Code review | `MAX_LINKS` = 65 536, `MAX_LINK_LEN` = 4096; over-limit links are dropped | `r03_hyperlink_table_is_bounded` |
| R-04 | Medium | The reply buffer (`Term::out`) grew without bound if the host never drained it (`cathode feed`, replaying a cast full of queries). | Code review | Capped at 64 KiB; further replies dropped | `r04_reply_queue_is_bounded` |
| R-05 | Medium | U+0080–U+009F (C1 controls arriving as UTF-8) have wcwidth 0, so they were glued onto the previous cell as "combining marks" — invisible junk that then leaked into text/HTML/SVG output. | Reading `print` against `char_width` | C1 code points are ignored like real terminals | `r05_c1_controls_are_ignored` |
| R-06 | Medium | SVG output could contain U+FFFE/U+FFFF, which are illegal in XML 1.0 → browsers refuse the whole image. | Spec check of the escaper | Replaced by U+FFFD in the shared escaper | `r06_svg_has_no_xml_invalid_characters` |
| R-07 | Medium (UX) | Key-script parser treated any `<...>` as a key spec, so typed text like `if a < b && c > d` or `<b>` either errored or sent the wrong key. | Typing realistic input | Only spec-shaped text (`<Name>`, `<C-x>`, `<wait N>`, …) is parsed; anything else is literal. Typos like `<Escc>` remain a hard error rather than silently typed | `r07_script_literal_angle_brackets` |
| R-08 | Low | OSC title unbounded (up to the 1 MB string cap). | Code review | Capped at 1024 chars | `r08_title_is_capped` |
| R-09 | High (DoS) | asciicast header/resize events could declare 10 000×10 000 (3 GB of cells) — `replay`/`player` would allocate it. | Hostile-input review of the cast reader | Dimensions capped at 1000; absurd `r` events are ignored | `r09_cast_dimensions_are_capped` |
| R-10 | Low | `resize` pushed lines into scrollback ignoring `scrollback_limit`. | Code review | Limit enforced | `r10_resize_respects_scrollback_limit` |
| R-11 | Medium (perf) | Hyperlink lookup was a linear scan; with R-03's cap that is O(n²) — 70 000 links took 31 s in a debug build. | Slow test | `HashMap` index keyed by (id, uri) → 0.37 s | same test as R-03 |
| R-12 | Low (UX) | No way to feed long input scripts (command-line length limit: `Argument list too long`). | Tried a 200 KB paste | `--keys-file FILE` | exercised in `demo.sh` |

## Checked and found correct (so the next reviewer need not repeat it)
Parser: byte-at-a-time == whole-buffer equivalence; CAN/SUB abort; ESC restart inside OSC; UTF-8 overlongs,
surrogates, >U+10FFFF, truncation before ESC; DEL ignored; param saturation (65535) and 32-param cap.
Screen: deferred wrap, wide-char split/overwrite/delete/insert/erase (no orphan halves, enforced by the
fuzz invariant), margins + origin mode, IL/DL outside region, BCE on erase *and* scroll, alt-screen cursor
save/restore, resize to 1×1 and back. Every query reply format was compared with xterm's documented text.

## Known limitations (deliberate, documented — not bugs)
* No left/right margins (DECSLRM), no sixel/graphics, no DECCOLM resizing, no VT52, no C1 8-bit controls (UTF-8 only).
* OSC 52 clipboard writes/reads are intentionally **not** honoured (clipboard injection is a security hazard).
* Emoji presentation selectors (U+FE0F) attach as zero-width marks but do not widen the cell.
* The `tmux` differential comparison (Phase 4) intentionally avoids the handful of behaviours where tmux
  and xterm legitimately differ; they are listed in `tests/tmux_oracle.rs`.

Fresh run-through after the fixes: `cargo test` (all suites) green; the 12 scenarios above re-run with no
remaining hit.
