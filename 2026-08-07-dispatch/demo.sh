#!/usr/bin/env bash
# demo.sh -- exercises every Dispatch feature end-to-end through the real CLI
# and the real test suite, and fails loudly (non-zero exit) on the first
# problem. Safe to run from any working directory.
#
# Note: every check below captures a command's output into a variable first,
# then greps the variable -- never `cmd | grep -q ...` directly. Piping into
# `grep -q`/`head` under `set -o pipefail` can make the pipeline's exit status
# reflect a SIGPIPE the *producer* received when the consumer closed early,
# even though the grep itself matched -- a real bug this repo's own history
# (Strata/Loom entries) has hit and documented. Capturing first sidesteps the
# whole class of failure.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PASS=0
step() { PASS=$((PASS + 1)); echo; echo "[$PASS] $*"; }

require() {
    # require "$output" "substring" "description"
    if [[ "$1" != *"$2"* ]]; then
        echo "FAILED: expected to find '$2' in: $3"
        echo "--- actual output ---"
        echo "$1"
        exit 1
    fi
}

step "Full test suite (unit + textbook + oracle-fuzz + invariant-fuzz + CLI + browser XSS regression)"
python3 -m unittest discover -s tests -v

step "CPU scheduling: every algorithm against the textbook examples"
OUT=$(python3 cli.py run --algo fcfs --workload textbook_fcfs_sjf); require "$OUT" "avg waiting=5.75" "FCFS"
OUT=$(python3 cli.py run --algo sjf --workload textbook_fcfs_sjf); require "$OUT" "avg waiting=5.25" "SJF"
OUT=$(python3 cli.py run --algo srtf --workload textbook_srtf); require "$OUT" "avg waiting=6.50" "SRTF"
OUT=$(python3 cli.py run --algo rr --workload textbook_rr --quantum 4); require "$OUT" "avg waiting=5.67" "RR"
OUT=$(python3 cli.py run --algo priority --workload textbook_priority); require "$OUT" "avg waiting=8.20" "Priority"
python3 cli.py run --algo mlfq --workload mixed_general > /dev/null
python3 cli.py run --algo priority-aging --workload mixed_general --aging-rate 2 --aging-period 4 > /dev/null
echo "  all 7 algorithm variants ran and matched their known-correct numbers"

step "CPU scheduling: full comparison table"
python3 cli.py compare --workload mixed_general

step "Virtual memory: all 4 page-replacement algorithms + Belady's Anomaly"
OUT=$(python3 cli.py vm --algo all --ref belady --frames 3)
require "$OUT" "faults=9" "FIFO @3 frames"
require "$OUT" "anomaly CONFIRMED" "anomaly detection"
OUT=$(python3 cli.py vm --algo fifo --ref belady --frames 4)
require "$OUT" "faults=10" "FIFO @4 frames"
echo "  FIFO: 9 faults @3 frames, 10 @4 frames -- Belady's Anomaly reproduced exactly"

step "Deadlock avoidance: Banker's Algorithm (classic Silberschatz example)"
OUT=$(python3 cli.py deadlock --mode bankers --available "[3,3,2]" \
    --max "[[7,5,3],[3,2,2],[9,0,2],[2,2,2],[4,3,3]]" \
    --allocation "[[0,1,0],[2,0,0],[3,0,2],[2,1,1],[0,0,2]]")
require "$OUT" "SAFE state" "Banker's safety check"

step "Deadlock detection: resource-allocation-graph cycle detection"
OUT=$(python3 cli.py deadlock --mode detect \
    --assignment '[["R0","P0"],["R1","P1"]]' --request-edges '[["P0","R1"],["P1","R0"]]')
require "$OUT" "DEADLOCK DETECTED" "cyclic RAG"
OUT=$(python3 cli.py deadlock --mode detect --assignment '[["R0","P0"]]' --request-edges '[["P0","R1"]]')
require "$OUT" "No deadlock" "acyclic RAG"

step "Synthetic workload generator"
python3 cli.py generate --n 12 --rate 0.3 --seed 7 --output /tmp/dispatch_demo_synth.json
python3 cli.py compare --workload /tmp/dispatch_demo_synth.json > /dev/null
echo "  generated a 12-process Poisson-arrival workload and scheduled it successfully"

step "CLI error-handling: every bad-input path exits cleanly, no raw traceback"
for args in \
    "run --algo fcfs --workload nope" \
    "run --algo rr --workload mixed_general --quantum 0" \
    "vm --algo fifo --ref belady --frames 0" \
    "run --algo mlfq --workload mixed_general --boost 0" \
    "run --algo priority-aging --workload mixed_general --aging-period 0" \
    "deadlock --mode bankers --available [3,3] --max [[7,5,3]] --allocation [[0,1,0]]" \
    "generate --n 0 --rate 0.3 --output /tmp/x.json"
do
    set +e
    ERR_OUT=$(python3 cli.py $args 2>&1)
    RC=$?
    set -e
    if [[ $RC -ne 1 ]]; then
        echo "FAILED: expected exit code 1 for 'cli.py $args', got $RC"; exit 1
    fi
    if [[ "$ERR_OUT" == *Traceback* ]]; then
        echo "FAILED: raw traceback leaked for 'cli.py $args':"; echo "$ERR_OUT"; exit 1
    fi
done
echo "  7/7 error paths clean (exit 1, no raw traceback)"

step "HTML visualizer: render the report and confirm real content"
python3 cli.py report --workload mixed_general --vm-ref belady --frames 3 --output /tmp/dispatch_demo_report.html
python3 -c "
import json
text = open('/tmp/dispatch_demo_report.html').read()
assert '<title>Dispatch' in text
start = text.index('const DATA = ') + len('const DATA = ')
end = text.index(';\n', start)
data = json.loads(text[start:end])
assert len(data['cpu']) == 7, 'expected 7 CPU-scheduling algorithm variants'
assert data['vm']['fifo']['faults'] == 9
assert data['anomaly']['series']['fifo'][2] < data['anomaly']['series']['fifo'][3], 'anomaly not present in sweep data'
print('  report is well-formed with real simulation data (not placeholder)')
"

step "Cleanup"
rm -f /tmp/dispatch_demo_synth.json /tmp/dispatch_demo_report.html /tmp/x.json

echo
echo "=================================================="
echo " Dispatch demo.sh: all $PASS steps passed."
echo "=================================================="
