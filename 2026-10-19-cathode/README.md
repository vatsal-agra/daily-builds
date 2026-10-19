# Cathode
A from-scratch terminal emulator core in Rust (zero dependencies): DEC escape-sequence parser,
screen model, real PTY host, and text / ANSI / HTML / SVG / JSON renderers.

**Status: Phase 2 (core build) done.** Required features working end-to-end and covered by 93 tests:

| # | Feature | Where | Proof |
|---|---------|-------|-------|
| 1 | VT parser (Williams state machine + UTF-8) | `src/parser.rs` | `tests/parser.rs` (21) |
| 2 | Screen model (cursor, regions, tabs, wide chars, alt screen, scrollback, resize) | `src/screen.rs`, `src/term.rs` | `tests/screen.rs` (41) |
| 3 | SGR / colours / OSC (title, palette, hyperlinks) / query replies | `src/term.rs` | `tests/sgr_render.rs` (17) |
| 4 | Real PTY host: runs vim, nano, less, sh; resize; replies written back | `src/pty.rs`, `src/session.rs` | `tests/pty.rs` (14) |

Try it: `cargo run --release -- run --keys 'ihello<Esc>' -- vim -u NONE -N`

See `PLAN.md` for the full design. (README is completed in Phase 6.)
