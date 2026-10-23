#!/usr/bin/env bash
# Gatecraft end-to-end demo: drives every feature through the real CLI and asserts on the output.
# usage: ./demo.sh            (exit status 0 only if every step passes)
set -u
cd "$(dirname "$0")"
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
go build -o "$OUT/gatecraft" ./cmd/gatecraft || { echo "build failed"; exit 1; }
GC="$OUT/gatecraft"
pass=0; fail=0

# step <name> <expected exit code> <required output substring> -- <command...>
step() {
  local name=$1 want=$2 needle=$3; shift 4
  local log="$OUT/step.log"
  "$@" >"$log" 2>&1; local code=$?
  if [ "$code" -eq "$want" ] && grep -qF -- "$needle" "$log"; then
    printf '  \033[32mPASS\033[0m  %s\n' "$name"; pass=$((pass+1))
  else
    printf '  \033[31mFAIL\033[0m  %s (exit %s, wanted %s, needle %q)\n' "$name" "$code" "$want" "$needle"
    sed 's/^/        | /' "$log" | head -20; fail=$((fail+1))
  fi
}
section() { printf '\n\033[1m%s\033[0m\n' "$1"; }

section "1. Frontend + elaboration (Verilog subset -> AIG)"
step "elaborate counter"                      0 "latches  8"            -- $GC elab examples/counter.v
step "parameter override -P W=4"              0 "latches  4"            -- $GC elab examples/counter.v -P W=4
step "hierarchy flattened (tinycpu)"          0 "latches  86"           -- $GC elab examples/tinycpu.v -names
step "critical path report"                   0 "critical path"         -- $GC elab examples/adder_rtl.v -timing
cat >"$OUT/w.v" <<'V'
module s(input [3:0] x, output [3:0] y); assign y = x; endmodule
module m(input [7:0] a, output [3:0] y); s u(.x(a), .y(y)); endmodule
V
step "port-width warning (truncation)"        0 "truncated"             -- $GC elab "$OUT/w.v"
cat >"$OUT/latch.v" <<'V'
module m(input a, input c, output reg y); always @* if (c) y = a; endmodule
V
step "latch inference diagnosed"              2 "latch inferred"        -- $GC elab "$OUT/latch.v"
cat >"$OUT/loop.v" <<'V'
module m(input a, output y); wire p, q; assign p = q & a; assign q = ~p; assign y = q; endmodule
V
step "combinational loop diagnosed"           2 "combinational loop"    -- $GC elab "$OUT/loop.v"
cat >"$OUT/async.v" <<'V'
module m(input clk, input r, output reg q); always @(posedge clk or posedge r) q <= 0; endmodule
V
step "unsupported construct explained"        2 "asynchronous reset"    -- $GC elab "$OUT/async.v"

section "2. Cycle-accurate simulation, testbench scripts, VCD"
step "counter testbench"                      0 "10 checks, 0 failed"   -- $GC sim examples/counter.v -tb examples/counter.tb -vcd "$OUT/c.vcd"
step "VCD has hierarchy + vars"               0 "\$enddefinitions"      -- cat "$OUT/c.vcd"
step "TinyCPU runs sum and Fibonacci"         0 "7 checks, 0 failed"    -- $GC sim examples/tinycpu.v -tb examples/tinycpu.tb -vcd "$OUT/cpu.vcd"
step "VCD scopes for submodules"              0 "\$scope module u_rf"   -- cat "$OUT/cpu.vcd"
step "FIFO behaves"                           0 "11 checks, 0 failed"   -- $GC sim examples/fifo4.v -tb examples/fifo4.tb
step "traffic light"                          0 "7 checks, 0 failed"    -- $GC sim examples/traffic.v -tb examples/traffic.tb
printf 'set rst 1\ntick\nexpect q 9\n' >"$OUT/bad.tb"
step "failing testbench -> exit 1"            1 "expected q == 9"       -- $GC sim examples/counter.v -tb "$OUT/bad.tb"

section "3. Optimiser (strash, rewrite, balance, SAT-sweeping, sequential cleanup)"
step "TinyCPU: 2275 -> 832 ANDs, proved"      0 "SAT-proved equivalent" -- $GC opt examples/tinycpu.v -o "$OUT/cpu.v"
step "stuck / duplicate / dead registers"     0 "removed register sticky" -- $GC opt examples/pipeline_redundant.v -o "$OUT/pipe.blif"
step "optimised netlist re-parses (Verilog)"  0 "latches"               -- $GC elab "$OUT/cpu.v"
step "optimised design still passes the TB"   0 "7 checks, 0 failed"    -- $GC sim examples/tinycpu.v -tb examples/tinycpu.tb -opt

section "4. SAT equivalence checking"
step "ripple-carry == Kogge-Stone adder"      0 "EQUIVALENT"            -- $GC equiv examples/adder_rtl.v examples/adder_kogge.v
step "buggy adder: counterexample"            1 "a=255 b=0 cin=1"       -- $GC equiv examples/adder_rtl.v examples/adder_buggy.v
step "counterexample replayed in simulator"   1 "difference CONFIRMED"  -- $GC equiv examples/adder_rtl.v examples/adder_buggy.v
step "popcount loop == popcount tree"         0 "EQUIVALENT"            -- $GC equiv examples/popcount_loop.v examples/popcount_tree.v
step "design == its optimised netlist"        0 "EQUIVALENT"            -- $GC equiv examples/tinycpu.v -opt
step "interface mismatch reported"            2 "interfaces differ"     -- $GC equiv examples/counter.v examples/adder_rtl.v
step "one-hot == binary FSM (for all time)"   0 "proved for all time"   -- $GC equiv examples/detect_onehot.v examples/detect_binary.v
step "mod-10 counters, different encodings"   0 "proved for all time"   -- $GC equiv examples/mod10_a.v examples/mod10_b.v
step "sequential bug: shortest trace"         1 "diverge at cycle 5"    -- $GC equiv examples/detect_binary.v examples/detect_bug.v -cex "$OUT/cex.tb"
step "cex script fails on the buggy design"   1 "expected found == 1"   -- $GC sim examples/detect_bug.v -tb "$OUT/cex.tb"
step "cex script passes on the reference"     0 "1 checks, 0 failed"    -- $GC sim examples/detect_binary.v -tb "$OUT/cex.tb"

section "5. Model checking: BMC + k-induction"
step "lock: BMC recovers the secret code"     1 "digit=3"               -- $GC check examples/lock.v -depth 10
step "lock: invariant proved by induction"    1 "PROVED   open_means_done" -- $GC check examples/lock.v -depth 10
step "FIFO invariants (with assumptions)"     0 "PROVED   pointer_gap"  -- $GC check examples/fifo4.v
step "traffic light never crashes"            0 "PROVED   no_crash"     -- $GC check examples/traffic.v
step "TinyCPU pc stays in ROM"                0 "PROVED"                -- $GC check examples/tinycpu.v
step "failing trace as VCD"                   1 "waveform:"             -- $GC check examples/lock.v -depth 10 -vcd "$OUT/lock"

section "6. LUT mapping (FPGA-style)"
step "4-LUT map, sim + SAT verified"          0 "formal check: LUT network" -- $GC map examples/tinycpu.v -k 4 -o "$OUT/cpu4.blif"
step "6-LUT map"                              0 "6-LUT mapping"         -- $GC map examples/tinycpu.v -k 6
step "BLIF has latches + LUTs"                0 ".latch"                -- cat "$OUT/cpu4.blif"
step "bad k rejected"                         2 "between 2 and 6"       -- $GC map examples/tinycpu.v -k 9

section "7. Export formats + round trips"
step "structural Verilog"                     0 "module top("           -- $GC emit examples/fifo4.v -format verilog
step "BLIF"                                   0 ".model top"            -- $GC emit examples/fifo4.v -format blif
step "AIGER"                                  0 "aag "                  -- $GC emit examples/fifo4.v -format aag
$GC emit examples/fifo4.v -format aag -o "$OUT/f.aag"
step "AIGER is a valid input"                 0 "latches"               -- $GC elab "$OUT/f.aag"
$GC emit examples/fifo4.v -format verilog -o "$OUT/fifo_rt.v" -opt >/dev/null 2>&1
step "emitted Verilog keeps its properties"   0 "PROVED   a0_count_bounded" -- $GC check "$OUT/fifo_rt.v"

section "8. HTML report with waveform viewer"
step "report generated"                       0 "wrote"                 -- $GC report examples/tinycpu.v -tb examples/tinycpu.tb -o "$OUT/report.html"
step "report has all sections"                0 "LUT mapping"           -- cat "$OUT/report.html"
if command -v node >/dev/null 2>&1 && [ -f tests/report_check.js ] && NODE_PATH=$(npm root -g 2>/dev/null) node -e "require('playwright')" 2>/dev/null; then
  step "report renders in headless Chromium"  0 "report OK"             -- env NODE_PATH="$(npm root -g)" node tests/report_check.js "$OUT/report.html"
else
  printf '  \033[33mSKIP\033[0m  headless-browser check (node/playwright not available)\n'
fi

section "9. Error handling"
step "no arguments -> usage"                  2 "usage: gatecraft"      -- $GC
step "unknown command"                        2 "unknown command"       -- $GC frobnicate
step "missing file"                           2 "no such file"          -- $GC elab nope.v
printf 'module m(input a, output y);\n  assign y = a +;\nendmodule\n' >"$OUT/syn.v"
step "syntax error with file:line:col"        2 "syn.v:2:17"            -- $GC elab "$OUT/syn.v"
: >"$OUT/empty.v"
step "empty file"                             2 "no modules found"      -- $GC elab "$OUT/empty.v"

printf '\n\033[1m%d passed, %d failed\033[0m\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
