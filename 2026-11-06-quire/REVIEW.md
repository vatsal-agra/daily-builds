# Adversarial review

Method: I attacked the Phase-2 build four ways — (1) a **mutation fuzzer** (`tools/fuzz.py`: byte flips,
truncation, deletions, insertions, splices over four real fixtures incl. encrypted ones, 20 s watchdog),
(2) a **hand-built feature gallery** (`tests/gallery.py`, 22 one-feature PDFs) diffed pixel-wise against
`pdftoppm`, (3) **differential text/crypto checks** against `pdftotext` and against PDFs encrypted by
independent code, and (4) a plain read-through for shortcuts. Everything below was *observed*, not guessed.

| # | Sev | Finding (how it showed up) | Fix | Regression test |
|---|-----|----------------------------|-----|-----------------|
| 1 | **CRITICAL** | **Infinite loop** in `CMap.split`: a 2-byte code truncated at the end of a string (or bytes outside every codespace) never advanced the cursor. Fuzzer: 3 of 100 mutants hung; any real PDF with an odd-length Identity-H string would too. | cursor always advances; zero/oversized codespaces ignored | `test_cmap_split_never_stalls` |
| 2 | **HIGH** | A corrupt embedded font raised `struct.error` out of the content interpreter and **aborted the whole page / text extraction** (39 of 120 mutants crashed). | every operator isolated (page keeps going); a bad glyph is skipped with a warning | `test_corrupt_font_does_not_abort_page`, fuzz smoke test |
| 3 | HIGH | **DeviceCMYK used `1-c-k`**: pure `0 1 1 0` rendered (255,0,0), poppler/Acrobat-style gives (237,28,36); every CMYK/Separation colour was visibly off (gallery `colors`: 4.0 % pixels wrong). | 16-corner multilinear conversion | gallery `colors` now 0.00 % |
| 4 | MED | CalRGB/CalGray treated as device spaces (gallery: (230,128,26) vs (255,75,65)). | gamma + matrix + white-point → sRGB | gallery `colors` |
| 5 | MED | 0-width / 0.5 pt hairlines straddled two pixel rows at 50 % grey (blurry). | poppler-style stroke adjustment for thin axis-aligned lines | gallery `strokes` 0.77 → 0.37 % |
| 6 | MED | Non-embedded base-14 fonts without `/Widths` advanced by the *substitute* font's metrics → whole lines mis-spaced. | built-in width tables (Helvetica, Helvetica-Bold, Times, Courier) | gallery `text_state` mad 15.2 → 8.9 |
| 7 | MED | **Annotations were never drawn** (stamps, form-field appearances, link borders) — a filled-in form rendered blank. | `/AP /N` fitted to `/Rect` incl. `/AS` states, Hidden/NoView flags, rotated matrices; link borders | gallery `annotations` |
| 8 | MED | Junk before `%PDF-` was treated as corruption → full rescan (and `repaired: yes`). | offsets are header-relative (Acrobat's rule) | `test_junk_before_header_is_not_a_repair` |
| 9 | MED | A dash array like `[0.0001]` on a long line produced millions of dashes (hang / OOM). | pathological patterns fall back to solid | `test_dash_bomb_terminates` |
| 10 | MED | A 14400×14400 pt page at 72 dpi allocated ≈600 MB. | refused with a clear "use a lower --dpi" error | `test_huge_page_refused` |
| 11 | MED | JPEG: Adobe CMYK was inverted *inside* the decoder, then inverted again by the PDF `/Decode` array → near-black image (found by looking at the gallery). Truncated headers raised `IndexError`. | decoder returns raw samples (PDF's Decode does the inversion); all failures are `JpegError` | gallery `jpeg_images` 13.5 → 0.06 %, `test_truncated_jpeg…` |
| 12 | LOW | Images upscaled with nearest-neighbour; poppler is bilinear below 400 % and nearest from 400 %. Measured the crossover experimentally (16 px source at 7 sizes). | same rule | gallery `images`, `jpeg_images` |
| 13 | LOW | Identity-H fonts without `/ToUnicode` extracted **no text**. | invert the embedded font's own cmap | — (manual) |
| 14 | LOW | Passwords for R2–R4 were UTF-8 encoded; the spec says PDFDocEncoding (≈Latin-1). | latin-1 for R≤4, UTF-8 for R5/6 | crypt tests |
| 15 | LOW | Soft masks / blend modes were silently ignored. | now emit a warning (still unsupported) | — |
| 16 | LOW | Non-PDF input said "cannot reconstruct: no catalog found". | "not a PDF file (or too damaged to recover)" | `test_garbage_input_raises_cleanly` |
| 17 | LOW | Leftover dead code (miter maths, a `Filter`/`F` hack in `filter_chain`, unused flatten flag). | removed | — |
| 19 | MED | Fuzz seeds 11, 14, 16: a mutated `/Encrypt` dictionary (wrong types, or a non-dictionary reached during xref reconstruction) raised bare `TypeError`/`AttributeError`. | malformed encryption dictionaries → `CryptError` | fuzz smoke test, `tools/fuzz.py 60 11` |
| 18 | LOW (found during build) | `text` printed a blank line between *every* line (each line was its own XY-cut block); glyph origins ignored the CTM so a flipped page came out upside-down. | paragraph logic from vertical gaps; text positions use the full matrix | `test_vs_pdftotext` |

Test-suite bugs I also caught: my incremental-update test used the wrong catalog object number; the CMYK
JPEG gallery case originally *asserted* the broken behaviour (#11) until compared against poppler.

## Deliberate decisions (not bugs)
* **CropBox is honoured** (what viewers show). `pdftoppm` defaults to MediaBox, so comparisons use `-cropbox`.
* The page/glyph rasteriser has **no hinting or gamma**; a pixel counts as wrong only if it differs by > 48/255
  from poppler's *and* from every neighbour (forgives 1 px shifts). Budgets per case are in `tests/test_gallery.py`.

## Known limitations (documented, warned about where detectable)
Soft masks, blend modes, mesh shadings (types 4–7), vertical writing, predefined CJK CMaps (no CMap data
shipped), JPX/JBIG2/CCITT images, Bold/Italic Times metrics for non-embedded fonts (regular table reused),
form-field *editing*, JavaScript. Linearized files parse through the normal `/Prev` chain (no sample available
to test against).

## Fresh run-through (gate)
After the fixes: `python3 -m unittest discover tests` green; `tools/gallery.py` — every case within budget;
`tools/fuzz.py` 7 seeds × 60 mutants → 0 crashes, 0 hangs (seed 11 found #19 on the way); none of the findings above reproduces.
