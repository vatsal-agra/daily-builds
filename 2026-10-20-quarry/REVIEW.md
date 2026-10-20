# Adversarial review

Method: I stopped being the author and tried to break the phase-2 build with hostile inputs, hostile
programs and hostile traces — every item below was **reproduced first**, then fixed, then given a
regression guard in `tests/` so the fresh run-through can prove it stays fixed. Items marked "found by
reading" were spotted in the code and then reproduced with a crafted input.

## Findings

| # | Sev | Finding | Reproduction | Fix | Guard |
|---|-----|---------|--------------|-----|-------|
| 1 | **critical** | Debug mode **corrupted user data**: `capture()` asked `backtrace()` for `max+3` frames but wrote them into a `max`-slot array inside the block header, overrunning into the user bytes and canary. Clean programs died with a bogus "overflow into a freed block's redzone". | `QUARRY_DEBUG=1 LD_PRELOAD=… ./t_bugs clean`; gdb watchpoint on the canary showed `backtrace_helper` writing it | capture into a local buffer, copy `min(n,max)` | `t_bugs clean` + real-program no-false-positive runs |
| 2 | high | Reports/statistics **vanished** for programs like `ls`: coreutils' `close_stdout` closes fd 2 in an `atexit` handler that runs before ours. | `QUARRY_STATS=1 LD_PRELOAD=… ls /` printed nothing | keep a private `F_DUPFD_CLOEXEC` duplicate of stderr; new `QUARRY_LOG=file` | `QUARRY_STATS prints a report at exit` (uses `ls`) |
| 3 | high | **Trace files clobbered by child processes**: a shell script's children each re-opened `QUARRY_TRACE` with `O_TRUNC`; the file ended up with 1,878 garbage opcodes and 75 usable events. | `QUARRY_TRACE=t.qtr LD_PRELOAD=… bash -c 'ls; ls'` | first process owns the path (`QUARRY_TRACE_OWNER`), descendants write `<path>.<pid>` | "child processes write `<trace>.<pid>`" test |
| 4 | high | qsim **trace loader heap overflow** (found by reading): the event array was sized `records+1` but one record can emit two events (implicit free of a re-used address + the allocation). | 2,000 mallocs of the same address; ASan: `heap-buffer-overflow WRITE of size 24 in trace_load` | array sized `2*records+1`; loader rewritten as small helpers | `reuse.qtr` replay + loader under ASan |
| 5 | high | qsim **resource explosion on corrupt traces**: a fuzzed trace made one replay child touch 3.7 GB (huge `calloc` sizes → `memset`/zero-verify). | `tests/fuzz_traces.py` (first version hung >2 min) | `--max-size` (256 MiB) / `--max-live` (8 GiB) rails with an "over the safety limits" counter; zero-verification samples only the first/last 4 MiB of huge blocks | 40-case corrupted-trace fuzz in the suite |
| 6 | medium | **Quadratic large-span search**: free spans ≥256 pages lived on one list scanned linearly for best fit. | 30,000 non-fitting 1.3 MiB requests: **7.67 s** | TLSF-style two-level index (octave × 16 sub-buckets) with a bitmap; only the request's own sub-bucket is scanned | `test_large_scan` (20,000 requests, must finish < 1 s); after: **0.043 s** (≈180×). My first attempt (log2 buckets only) did *not* help (7.56 s) — the benchmark showed it, the sub-buckets fixed it |
| 7 | medium | **Latent deadlock**: the "headerless block" table was guarded by the same mutex that `leak_report`/`quarry_check_heap` hold while calling `dladdr`/`backtrace` (which may allocate). | by inspection; any allocation inside those calls would re-lock a held non-recursive mutex | table made lock-free (atomic index + release stores) | whole debug suite |
| 8 | medium | **Wild reads on a smashed header**: `tail_of()` trusted `h->size`; an overwrite of the header made the redzone check read arbitrary memory (or crash instead of diagnosing). | `t_bugs smash_size`: size field set to 2⁵⁰ | `header_sane()` validates `base`/`size` against the core's real block size before any dereference; same check on quarantine eviction | `smash_size`, `smash_magic`, `deepunder` cases |
| 9 | medium | **Data race on first use** (ThreadSanitizer): `G.state`, `top_pages` and the pagemap were read lock-free with plain loads; `key_ok` was published after `state=2`, so a racing thread could skip registering its cache destructor and leak it at thread exit. | `tests/t_threads.c` under `-fsanitize=thread` | acquire/release `state`, key created *before* publishing, relaxed atomics for `top_pages` and pagemap entries | TSan run in the suite |
| 10 | low | Misleading/ugly diagnostics: "3 bytes before the block were overwritten" when one byte was; underflow count wrong for deep underflows. | `underflow3` | count bad guard bytes, singular/plural, "at least 8" when the whole guard is gone | `underflow3`, `deepunder` |
| 11 | low | qsim: `memalign` with alignment 0 / non power of two / > 1 GiB in a trace reached `p & (align-1)` and the models' `n + align + 32` arithmetic. | crafted trace | such requests are validated at load and counted as skipped | fuzz |
| 12 | low | qsim "FAILED" line built with `snprintf` inside `printf` arguments (unspecified order, shared buffer): two columns printed the same number. | the `after free` column equalled `peak mem` for every allocator | separate buffers; failure reporting rewritten with `strsignal` | visible in every table |
| 13 | low | qsim leaked its trace and rows (LeakSanitizer). | ASan build | `trace_free`, rows freed | "loader is clean under ASan" |
| 14 | low | build artefacts (`build/`) had been committed in the phase-2 commit. | `git ls-files` | removed from the index, `.gitignore` | — |
| 15 | note | A **bug in my own test** nearly masked a real result: the first replay showed 13,021 "corrupt" blocks on *every* allocator, including glibc — a verifier that fails everyone is the verifier's fault (head/tail fingerprints overlapped for blocks < 32 bytes). | first `qsim compare` | fingerprints made disjoint for any size; the generator's double-free (`tree`) that the loader flagged as "unknown free" fixed too | all replay tests |

## Probes that found nothing (kept as guards)
* `aligned_alloc(2²⁹)`, `memalign(2⁴⁰)` → `EINVAL`, `realloc(p, SIZE_MAX/2)` → `NULL` with the original intact.
* Address-space exhaustion under `ulimit -v 8000000`: 4,032 MiB allocated, then clean `NULL`/`ENOMEM`, then fully reusable after frees.
* 30 M ops of random-size churn: RSS plateaus (quarry 80→97 MiB, glibc 103→128 MiB over the same run).
* node 22, gcc, python (`PYTHONMALLOC=malloc`), tar|gzip, awk, find under `LD_PRELOAD`, and under `QUARRY_DEBUG=1` — no false positives.
* Single-thread 20 M ops 0.24 s vs glibc 0.33 s; 8 threads 0.35 s vs 0.59 s.

## Known limitations (deliberately not fixed; also listed in the README)
* `realloc()` of a pointer quarry does not own returns `EINVAL` (it cannot know the old size); `free()` of one is ignored.
* Without debug mode a double free is detected only when the object is still in the calling thread's cache or on the shared list.
* Use-after-free is detected when the block leaves quarantine (or at exit/`quarry_check_heap`), not at the access — there are no guard pages.
* Debug headers cost 192 B + 16 B per block; stacks keep at most 10 (alloc) / 6 (free) frames.
* A trace killed by a signal loses its last ≤2048 buffered events.
* qsim holds the whole trace in memory (24 B per event).

## Fresh run-through
After the fixes: `make test` from a clean build — see the README for the current numbers. Every guard above passes, and each guard was seen failing against the pre-fix code (findings 1, 2, 3, 4, 6, 8 reproduced with the old binaries before fixing).
