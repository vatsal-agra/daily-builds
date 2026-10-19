# Cathode
A from-scratch terminal emulator core in Rust (zero dependencies): DEC escape-sequence parser,
screen model, real PTY host, and text / ANSI / HTML / SVG / JSON renderers.

**Status: Phase 4 (stretch + polish) done.** All four stretch features shipped: asciicast record/replay + HTML
player, scrollback/reflow on resize, the tmux differential oracle (found 3 real bugs, see `REVIEW.md`), and the input
encoder (modifiers, mouse, bracketed paste, focus). 165 tests. README is completed in Phase 6.

See `PLAN.md` for the design and `REVIEW.md` for the adversarial reviews.
