# Quire
*Work in progress — Phase 2 (core build) complete. See [PLAN.md](PLAN.md).*

A from-scratch PDF reader, text extractor and renderer (Python 3 stdlib only).

## Status
- [x] Robust parser: xref tables / xref streams / object streams / incremental updates / reconstruction of damaged files
- [x] Decryption: RC4-40/128, AES-128, AES-256 (R5 + R6), user + owner passwords
- [x] Text extraction with reading order (matches `pdftotext` ≥ 96 % on tokens)
- [x] Renderer: own AA rasteriser + TrueType/CFF outlines (≤ 0.5 % differing pixels vs `pdftoppm`)

## Try it
```
./quire.sh info tests/fixtures/chrome.pdf
./quire.sh text tests/fixtures/chrome.pdf
./quire.sh render tests/fixtures/chrome.pdf -o page.png --dpi 100
./quire.sh text tests/fixtures/enc_aes256.pdf -p userpw
python3 -m unittest tests.test_core
```
