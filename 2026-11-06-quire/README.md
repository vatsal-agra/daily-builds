# Quire
*Work in progress — Phase 4 (stretch + polish) complete. See [PLAN.md](PLAN.md) and [REVIEW.md](REVIEW.md).*

A from-scratch PDF reader, text extractor and renderer (Python 3 stdlib only).

## Status
- [x] Required: robust parser · decryption · text extraction · renderer
- [x] Stretch shipped: JPEG decoder (baseline + progressive), CFF/Type 2 + Type 1 fonts, search with highlight boxes, HTML inspector
- [x] Polish: CLI error handling, `info --json`, `--mediabox`, annotations, malformed-input hardening (fuzzed)

## Try it
```
./quire.sh info tests/fixtures/chrome.pdf
./quire.sh text tests/fixtures/chrome.pdf
./quire.sh render tests/fixtures/chrome.pdf -o page.png --dpi 100 --highlight "lazy dog"
./quire.sh report tests/fixtures/chrome.pdf -o report.html
./quire.sh text tests/fixtures/enc_aes256.pdf -p userpw
```
