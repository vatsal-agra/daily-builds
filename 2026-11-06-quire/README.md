# Quire
*Work in progress — Phase 3 (adversarial review) complete. See [PLAN.md](PLAN.md) and [REVIEW.md](REVIEW.md).*

A from-scratch PDF reader, text extractor and renderer (Python 3 stdlib only).

## Status
- [x] Robust parser: xref tables / streams / object streams / incremental updates / reconstruction
- [x] Decryption: RC4-40/128, AES-128, AES-256 (R5 + R6), user + owner passwords
- [x] Text extraction with reading order and search
- [x] Renderer: own AA rasteriser, TrueType / CFF / Type 1 outlines, JPEG, shadings, patterns, annotations
- [x] Adversarial review: 18 findings fixed (see REVIEW.md)

## Try it
```
./quire.sh info tests/fixtures/chrome.pdf
./quire.sh text tests/fixtures/chrome.pdf
./quire.sh render tests/fixtures/chrome.pdf -o page.png --dpi 100 --highlight "lazy dog"
./quire.sh text tests/fixtures/enc_aes256.pdf -p userpw
python3 -m unittest discover tests
```
