# Quire — a from-scratch PDF reader, text extractor and renderer

## Concept
Quire opens real-world PDFs (Chromium, LibreOffice, Word-style producers, encrypted, corrupted,
incrementally-updated) using only the Python 3 standard library, then does three things with them:
**dumps their structure**, **extracts text in reading order**, and **rasterises pages to PNG** with its
own anti-aliased scanline rasteriser and its own TrueType/CFF glyph-outline parsers.

## Why it's interesting
PDF is a hostile format: a text-ish grammar over binary streams, three generations of cross-reference
(tables, streams, object streams), incremental updates, five encryption schemes, font programs embedded
in subsets, and a graphics model (CTM, clipping, even-odd/non-zero fills) that has to be interpreted
exactly. The repo has built compilers, filesystems and GCs, but never a *file-format reader of this
depth*. It also has two excellent independent oracles on this machine — `pdftotext` and `pdftoppm`
(poppler) — so "works" is measurable, not asserted.

## Architecture (all under `quire/`)
| module | job |
|---|---|
| `objects.py` | PDF object model (Name, Ref, Stream, Dict helpers) |
| `lexer.py` | tokenizer + object parser (strings, hex, names with `#xx`, dict/array, inline images) |
| `filters.py` | Flate (+PNG/TIFF predictors), ASCIIHex, ASCII85, LZW, RunLength, DCT passthrough |
| `crypt.py` | RC4, AES-128/256 CBC (own AES), key derivation R2–R6, per-object keys |
| `document.py` | xref tables/streams/object streams/Prev chains/hybrid, **xref reconstruction**, page tree |
| `fonts.py` | encodings, glyph list, ToUnicode CMaps, CID fonts, widths, font-program dispatch |
| `truetype.py`, `cff.py` | glyf/loca/cmap/hmtx parsing; CFF Type 2 charstring interpreter |
| `content.py` | content-stream interpreter producing a device-agnostic op stream |
| `text.py` | glyph runs → lines → reading order, `search` with bounding boxes |
| `raster.py` | AA scanline polygon filler, stroker (joins/caps/dashes), clip masks, PNG writer |
| `render.py` | page → pixels (paths, text, images, colour spaces, soft masks, shadings-lite) |
| `jpeg.py` | baseline+progressive JPEG decoder (stretch) |
| `report.py` | self-contained HTML inspector (stretch) |
| `cli.py` | `quire info|dump|text|render|search|decrypt|report` |

## Features
1. **Robust parser (REQUIRED)** — xref tables, xref streams, object streams, `/Prev` chains, hybrid
   files, all stream filters, predictors, and *reconstruction by scanning* when startxref/xref is
   corrupt or truncated.
2. **Decryption (REQUIRED)** — RC4-40, RC4-128, AESV2, AESV3 (R5/R6) with user/owner passwords,
   empty-password auto-open, permissions reporting, `decrypt` command writing a clean PDF.
3. **Text extraction (REQUIRED)** — fonts/encodings/ToUnicode/CID, text matrix tracking, line and
   column-aware reading order; scored against `pdftotext`.
4. **Renderer (REQUIRED)** — own rasteriser + TrueType glyph outlines; paths, clipping, colour spaces,
   Flate images with SMask; scored pixel-wise against `pdftoppm`.
5. **JPEG decoder (stretch)** — baseline + progressive DCT images in renderer.
6. **CFF / Type 2 charstrings (stretch)** — OpenType-CFF and Type1C fonts render and extract.
7. **HTML inspector report (stretch)** — object tree browser, page thumbnails, fonts, xref map.
8. **Text search with highlight boxes (stretch)** — `quire search` returns page + bbox, optionally
   draws highlights on the rendered PNG.
