#!/usr/bin/env bash
# RegexLab demo: exercises every feature. Run from the project folder:
#   bash demo.sh
set -euo pipefail
cd "$(dirname "$0")"
rx() { python3 -m rxlab "$@"; }
hr() { printf '\n\033[1;36m── %s ──────────────────────────\033[0m\n' "$1"; }

hr "parse: AST dump"
rx parse '(\d+)-(\d+)'

hr "search / match / fullmatch with captures"
rx search '(\d+)-(\d+)' 'call 555-1234 now'
rx fullmatch '\w+@\w+\.\w+' 'me@example.com'

hr "findall"
rx findall '\b\w{4}\b' 'this line has some four char words'

hr "trace: watch the Pike VM threads in the terminal"
rx trace '\bcat' 'a cat'

hr "dfa: subset construction + Hopcroft minimization"
rx dfa '(a|b)*abb' --table --text ababb

hr "explain: plain-English breakdown"
rx explain '(\d{1,3}\.){3}\d{1,3}|localhost'

hr "gen: random verified matching strings"
rx gen '(\d{1,3}\.){3}\d{1,3}' -n 5 --seed 42

hr "ReDoS resistance: (a+)+\$ on 60 a's + X (backtrackers choke here)"
time rx search '(a+)+$' "$(printf 'a%.0s' {1..60})X" || true

hr "viz: interactive single-file HTML visualizer"
rx viz '(a|b)*abb' -o regexlab-demo.html --text ababb
ls -la regexlab-demo.html

hr "fuzz: differential check vs Python's re (800 random patterns)"
rx fuzz -n 800 --seed 1

hr "full test suite"
python3 -m unittest discover -s tests -v 2>&1 | tail -5

printf '\n\033[1;32mdemo complete — open regexlab-demo.html in a browser\033[0m\n'
