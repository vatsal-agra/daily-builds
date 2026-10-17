# REVIEW — adversarial pass (Phase 3)

I attacked the Phase 2 build as a hostile reviewer: ran the CLI against empty/odd inputs, crafted malicious
containers, timed pathological inputs, and re-read every file looking for shortcuts. Findings, severity, and
the fix for each. Every item below was reproduced before being fixed.

| # | Sev | Finding (reproduced) | Fix |
|---|-----|----------------------|-----|
| R1 | **High** | **Allocation bomb.** A 17-byte `KOL1` file declaring 1 GiB makes `cm` allocate ~2 GiB (history buffer + output) *before* noticing the stream is garbage. Any method can be made to over-allocate this way. | Each method has a hard maximum expansion ratio (deflate 1032:1 by construction, bwt ≈7.4k:1, cm ≈1.4k:1, rans capped). `Decode` rejects a declared size that exceeds `(payload+64)·ratio` *before allocating*. The encoder enforces the same bound so Kolmo can never write a file it would refuse to read; `auto` simply skips a method that cannot honour it. |
| R2 | **High** | **`heat` emits broken HTML.** Tooltip text used `%q` of the byte, so the byte `"` produced `title="'"' · 7 bits"` — the attribute terminates early (reproduced with input `say "hi"`). | Tooltips are built then `html.EscapeString`'d. |
| R3 | Med | `heat` output is ~55 bytes of HTML **per input byte** (1.1 MB for a 20 KB file; 11 MB at the default cap) — an unusable report for real files. | The text and one cost character per byte are embedded once and a tiny script merges runs of equal shading in the browser: a 20 KB file now yields a 53 KB report (was 975 KB). Verified rendering in headless Chromium, zero page errors. |
| R4 | Med | `cm` decoder accepted truncated payloads and trailing garbage (`overrun` only trips >8 bytes past end). A payload with junk appended decoded "successfully". | The arithmetic decoder consumes *exactly* `len(payload)` bytes by construction; `Decode` now requires `pos == len(payload)`. |
| R5 | Med | Compressing a file > 1 GiB succeeds but produces a file Kolmo refuses to decode (`MaxOriginal`). | `compress` rejects oversize input up front with a clear message. |
| R6 | Med | `-m auto` always runs the ~3.5 s/MB `cm` model: a 200 MB file would sit for ~12 minutes with no warning. | `auto` skips `cm` above 32 MiB (and says so); `-m cm` still forces it. |
| R7 | Low | Error output printed `kolmo: kolmo: not a valid KOL1 file` (the sentinel's own prefix doubled). | Sentinel messages no longer carry the prefix. |
| R8 | Low | `bench` with no files printed `expected 1..-1 file arguments`. | Human-readable arity errors. |
| R9 | Low | `deflate.writeBlock` had a leftover `if len(raw) <= 65535 \|\| true` hack when estimating stored cost. | Removed; the estimate is exact for multi-block stored output. |
| R10 | Low | `container_test.go` shipped a placeholder test (`TestGzipInputAccepted` asserted nothing). | Replaced with a real round trip through `Decode` of a genuine gzip member. |
| R11 | Low | BWT uses one Huffman table per block, so it lands ~5% behind `bzip2` (80 729 B vs 77 083 B on the same file). A lazy shortcut — bzip2 uses up to 6 tables selected per 50-symbol group. | Addressed in Phase 4 as stretch feature #8 (multi-table Huffman with iterative table refinement). |

Things I attacked that **held up** (kept as regression tests in Phase 5): 3000+ mutated/truncated/garbage inputs
into inflate and the BWT decoder (no panic, no hang); empty and 1-byte inputs through every method; 4 MB of
random 4-letter "DNA" at level 9 (4.9 s — a bounded hash chain, not quadratic); 8 MB of zeros through BWT
(1.4 s, the doubling sort converges); period-1000 data; stored-block boundaries at 65535/65536 bytes;
concatenated gzip members; flipping any one bit of a container is always detected (CRC-32 or decoder error).

**Gate:** a fresh run-through of every item above now passes (regression tests: `TestSizeBombRejectedBeforeAllocation`, `TestEncoderHonoursDecoderBound`, `TestTrailingGarbageAndTruncationRejected`; CLI cases in `demo.sh`, Phase 5).
