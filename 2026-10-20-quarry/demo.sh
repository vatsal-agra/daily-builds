#!/usr/bin/env bash
# A guided tour: build, drop quarry under real programs, catch bugs, record a trace, replay it.
set -e
cd "$(dirname "$0")"
make -s
Q=tools/quarry
step() { printf '\n\033[1m# %s\033[0m\n' "$1"; }

step "1. Run real programs on top of quarry (no recompilation)"
$Q --stats -- ls /usr/include 2>&1 >/dev/null | head -8
$Q -- python3 -c 'print(sum(i*i for i in range(10**6)))'

step "2. Debug mode catches a heap overflow"
$Q --debug -- build/t_bugs overflow 2>&1 | head -12 || true

step "3. ...a double free, with both stacks"
$Q --debug -- build/t_bugs doublefree 2>&1 | head -16 || true

step "4. ...and a leak, symbolised"
$Q --debug -- build/t_bugs leak 2>&1 | python3 tools/qsym.py --exe build/t_bugs | head -9

step "5. Record what python3 allocates, then replay it on five allocators"
T=$(mktemp -d)
$Q --trace "$T/py.qtr" -- python3 -c 'import json; print(len(json.dumps([{"k": i, "v": [i]*8} for i in range(60000)])))' >/dev/null
build/qsim info "$T/py.qtr" | head -6
build/qsim compare "$T/py.qtr" --reps 3

step "6. Generate a workload that fragments, and watch it in the browser report"
build/qgen mixed -n 300000 -o "$T/mixed.qtr"
build/qsim compare "$T/mixed.qtr" --html quarry-report.html
echo "open quarry-report.html"
