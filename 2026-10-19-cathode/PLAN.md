# Cathode — a from-scratch terminal emulator core (Rust, zero dependencies)

## Concept
Every program that draws on a terminal (vim, less, top, ls --color) talks to an
invisible machine: a byte-stream parser plus a grid of cells. Cathode *is* that
machine. It spawns real programs on a real pseudo-terminal (PTY), parses their
output with a DEC-style escape-sequence state machine, maintains the screen
(grid, cursor, scroll regions, alt screen, scrollback, colors, wide chars) and
renders the result to text / ANSI / HTML / SVG. It also records sessions in the
asciicast v2 format and replays them.

## Why it's interesting
- Nothing in this repo's history touches the terminal layer (no VT100, no PTY).
- Correctness is checkable against a real oracle: `tmux` is itself a terminal
  emulator, so the same byte stream can be fed to both and screens diffed.
- Real programs (vim, nano, less, top) are the acceptance tests.
- Zero dependencies: even `openpty`/`fork`/`ioctl` are bound by hand via `extern "C"`.

## Architecture
```
src/
  parser.rs    Paul Williams' DEC ANSI state machine + incremental UTF-8 decoder -> Action events
  width.rs     wcwidth: combining (0), wide/emoji (2), control, from range tables
  color.rs     Color enum (Default/Indexed/Rgb), xterm 256 palette
  cell.rs      Cell + Attrs (bold, dim, italic, underline, blink, inverse, hidden, strike)
  screen.rs    Grid, cursor, modes, scroll region, tabs, charsets, alt screen, scrollback, reflow
  term.rs      Terminal = Parser + Screen; dispatches actions; produces query replies
  pty.rs       libc FFI: posix_openpt/fork/exec/ioctl(TIOCSWINSZ)/poll/waitpid
  render.rs    text / ANSI / HTML / SVG renderers
  cast.rs      asciicast v2 writer + reader + replayer
  input.rs     key -> bytes encoder (cursor keys app/normal mode, mouse SGR, bracketed paste)
  main.rs      CLI: run, feed, replay, record, render, diff-tmux
tests/         integration tests (parser, screen, PTY, tmux oracle, golden)
demo.sh        end-to-end demo
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | **VT parser**: full Williams state machine (CSI/OSC/DCS/ESC, params + subparams `:`, intermediates, C0 in-sequence execution, CAN/SUB abort), incremental UTF-8 across chunk boundaries with replacement chars | **required** |
| 2 | **Screen model**: cursor movement (CUU/CUD/CUF/CUB/CUP/CHA/VPA/HPA/CNL/CPL/NEL/IND/RI), erase (ED/EL/ECH), insert/delete (ICH/DCH/IL/DL), scroll regions DECSTBM + SU/SD, tab stops (HTS/TBC/CHT/CBT), DECAWM deferred wrap, DECOM origin mode, IRM, LNM, DECSC/DECRC, DEC special graphics charset (G0/G1, SO/SI), alt screen (47/1047/1049), RIS/DECSTR, DECALN, wide + combining chars | **required** |
| 3 | **SGR + colors**: 16/256/truecolor (`;` and `:` forms), all attributes and resets, OSC 0/2 title, OSC 8 hyperlinks, OSC 4/10/11 palette queries, background-color-erase | **required** |
| 4 | **Real PTY host**: spawn any program on a pseudo-terminal, TERM/COLUMNS/LINES, window resize (TIOCSWINSZ + SIGWINCH), replies to DSR/CPR/DA1/DA2/XTVERSION/DECRQM written back to the child, timed run-then-snapshot, exit status | **required** |
| 5 | **Renderers**: plain text, ANSI re-serialisation (round-trip), self-contained HTML (light/dark, colors, attrs, cursor, links), SVG | **required-adjacent** (needed for 4's output; HTML/SVG counted as part of #3 gates) |
| 6 | **asciicast v2** record + replay (with idle-time cap and speed) and an HTML player export | stretch |
| 7 | **Scrollback + resize reflow** (soft-wrap tracking, rewrap on width change) | stretch |
| 8 | **tmux differential oracle**: feed identical bytes to Cathode and to tmux, compare screen dumps cell-by-cell; fuzzed corpus | stretch |
| 9 | **Input encoder**: key names → bytes (app cursor mode, modifiers), SGR mouse, bracketed paste, focus events | stretch |

Required: 1, 2, 3, 4. Stretch: 6, 7, 8, 9 (5 is the shared output layer).

**Outcome (Phase 6):** all four required features and all four stretch features shipped; see README.md for the
final feature list and REVIEW.md for the two adversarial passes.
