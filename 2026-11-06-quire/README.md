# Quire

**A PDF reader, text extractor and renderer written from scratch in Python 3 — standard library only.**
Point it at a real-world PDF (Chromium, LibreOffice, encrypted, damaged, incrementally updated…) and it will
dump its structure, pull out text in reading order, search it, and rasterise pages to PNG with its own
anti-aliased rasteriser and its own font parsers. No PyPDF, no Pillow, no Cairo, no `zlib`-wrapper libraries
beyond `zlib`/`hashlib` from the stdlib (AES is implemented here; hashlib only supplies MD5/SHA-2).

```
$ ./quire.sh info tests/fixtures/enc_aes256.pdf -p userpw
Pages:       2
Encryption:  AES-256 (V5 R6), opened as user
Repaired:    no
$ ./quire.sh text tests/fixtures/chrome.pdf | head -3
Quire Test Document
The quick brown fox jumps over the lazy dog. Pack my box with five dozen liquor jugs.
$ ./quire.sh render tests/fixtures/chrome.pdf -o page.png --dpi 100 --highlight "lazy dog"
```

## How to run

Requires Python ≥ 3.9. Nothing to install.

| command | what it does |
|---|---|
| `./quire.sh info FILE [--json]` | version, page sizes, metadata, encryption + permissions, repair status |
| `./quire.sh text FILE [--pages 1,3-5] [-o out.txt]` | text in reading order (columns handled), ligatures expanded |
| `./quire.sh search FILE "query"` | every match with page + bounding box (PDF user space) |
| `./quire.sh render FILE [--pages 1-3] [--dpi 150] [--highlight TEXT] [--mediabox] -o out.png` | PNG per page |
| `./quire.sh decrypt FILE out.pdf [--compress]` | clean, decrypted copy (optionally with object streams + xref stream) |
| `./quire.sh report FILE -o report.html` | self-contained HTML inspector (thumbnails, text search, fonts, file-layout map, object browser) |
| `./quire.sh dump FILE [N] [--stream]` | object table / one object / its decoded stream |

Encrypted files: `-p PASSWORD` (user or owner; the empty user password opens automatically).
Run the whole gate with **`./verify.sh`** (`--quick` skips fuzzing and the browser check).

## Feature list

**Parser** — tokenizer + object parser tolerant of real-world sloppiness · classic xref tables, xref streams, object
streams, `/Prev` chains and hybrid files · **xref reconstruction** by scanning when `startxref`/the table is wrong,
the file is truncated, or an object is unreadable (also works for encrypted files) · junk before `%PDF-` ·
Flate (+ PNG/TIFF predictors, partial recovery of corrupt tails), LZW, ASCII85, ASCIIHex, RunLength · page tree with
inheritance and cycle protection · optional-content (hidden layers).

**Encryption** — RC4-40, RC4-128, AES-128 (V4), AES-256 (R5 and R6 with the hardened SHA-256/384/512 hash) ·
user **and** owner passwords · empty-password auto-open · crypt filters (`Identity`), `EncryptMetadata`,
permission flags · objects inside object streams · `decrypt` writes a clean copy.

**Text** — all simple-font encodings (Standard/WinAnsi/MacRoman/Differences, glyph-name → Unicode), `ToUnicode`
CMaps, CID fonts (Identity-H, embedded CMaps, `W` widths, reverse-cmap fallback), Type 3 fonts · word/line
assembly from glyph geometry · recursive XY-cut for **column-aware reading order** · rotated pages and text ·
search with page-space rectangles and on-image highlighting.

**Rendering** — scanline rasteriser with 4×-vertical/exact-horizontal coverage, exact non-zero and even-odd
winding, clip masks · stroker (caps, joins, miter limit, dashes, hairline snapping) · TrueType (`glyf`, composite
glyphs), **CFF/Type 2** (OpenType-CFF, bare Type1C, CID-keyed) and **Type 1** (eexec) outlines · colour spaces:
Gray/RGB/CMYK, Cal*, Lab, ICCBased, Indexed, Separation/DeviceN with PDF functions (types 0, 2, 3, 4) ·
images: Flate/LZW/etc. at 1/2/4/8/16 bpc, `/SMask`, `/Mask` (stencil & colour-key), image masks, inline images,
**JPEG** (baseline + progressive, subsampling with libjpeg's fancy upsampling, restart markers, Adobe CMYK/YCCK) ·
axial/radial/function shadings, tiling patterns (coloured and uncoloured) · form XObjects, constant alpha, page
`/Rotate`, CropBox, annotation appearance streams (+ link borders).

**Tooling** — HTML inspector · mutation fuzzer (`tools/fuzz.py`) · poppler comparison tools
(`tools/compare.py`, `tools/gallery.py`) · fixture generators (`tools/make_fixtures.py`).

## How it was verified

`./verify.sh` → **ALL GREEN** (21 stages). The independent oracles are poppler's `pdftotext`/`pdftoppm` and
Chromium/LibreOffice as *producers* of real files:

* **73 tests** — lexer/filters/xref-stream widths/incremental updates/reconstruction; AES against FIPS-197 vectors
  and RC4 against RFC vectors; every encryption flavour × user/owner/wrong/empty password; a test-only encrypting
  writer (AES-128 + **object streams** + xref stream — which poppler must decrypt too); text vs `pdftotext`
  (≥ 95 % token match; actually 97–100 %); 22-case rendering gallery vs `pdftoppm`; JPEG flavours; rasteriser
  unit tests; CLI error paths; HTML-injection safety of the report.
* **Pixels vs poppler** (a pixel is "wrong" only if it differs by > 48/255 from the reference *and* from every
  neighbour): real pages 0.2–0.5 % wrong; gallery cases 0.0–0.5 % (non-embedded fonts excepted — poppler
  substitutes different outlines).
* **Fuzzing**: 15 seeds × 60–80 mutants (flips, truncations, deletions, splices; encrypted files included) →
  0 crashes, 0 hangs after the fixes in [REVIEW.md](REVIEW.md) (which also lists all 19 bugs the review found).
* **Inspector** loaded in headless Chromium at 1280 px and 390 px (light/dark): tabs, search, object browser,
  no console errors, no horizontal overflow.

## Why I chose this today

The repo already holds compilers, filesystems, garbage collectors, crypto and a computer-algebra system — but no
*file-format reader of this depth*. PDF is the perfect adversary: a text grammar wrapped around binary streams,
three generations of cross-referencing, five encryption schemes, embedded font programs in three formats, and a
graphics model that has to be interpreted exactly. It also has an unusually good property for an autonomous
build: poppler on the same machine is an independent oracle, so "it works" is a number, not a feeling.

## Limitations (honest list)

Soft masks and blend modes (drawn unmasked/Normal, with a warning) · mesh shadings (types 4–7) · vertical
writing · predefined CJK CMaps (no CMap data shipped) · JPX/JBIG2/CCITT images · no font hinting or text gamma ·
Bold/Italic Times metrics for *non-embedded* fonts reuse the regular table, and non-embedded fonts are
substituted with DejaVu when it is installed (otherwise their glyphs aren't drawn) · form *filling*, JavaScript ·
pure-Python speed: ≈ 0.2 s for a text page at 72 dpi, ≈ 5 s for a dense 6 000-path page at 150 dpi, AES-256
decryption ≈ 0.5 MB/s.

## Where a human could take this next

1. **Transparency groups** — soft masks, blend modes, isolated/knockout groups (the biggest visible gap).
2. **Speed**: numpy-free but vectorised inner loops, glyph-bitmap caching, or a C accelerator for `scan()`/AES.
3. **Writing PDFs** — the writer already round-trips objects; add page merge/split, redaction (the search
   rectangles are already there), form filling, incremental saves, re-encryption.
4. **CJK**: ship Adobe's CMap resources and vertical metrics; JPX via a JPEG-2000 decoder.
5. **Linearized-file fast path** and lazy page loading for 10 000-page documents.
6. **Tagged-PDF structure tree** for semantic text extraction (headings, tables, reading order from the author).
7. **Table detection** on top of the line/word geometry the extractor already builds.

## Layout

```
quire/           the library (lexer, document, crypt, fonts, truetype, cff, type1, jpeg, content, text, raster, render, report, cli)
tests/           unit + integration tests, gallery generator, fixtures (real Chromium/LibreOffice PDFs, encrypted variants, JPEGs)
tools/           fuzz.py, compare.py, gallery.py, make_fixtures.py, check_report.js
verify.sh        the full gate        PLAN.md / REVIEW.md   design + adversarial review
```
