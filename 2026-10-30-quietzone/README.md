# Quietzone
A from-scratch QR code laboratory in Go (stdlib only). See [PLAN.md](PLAN.md).

**Status: Phase 2 complete — the four required features work end to end.**

| Required feature | State |
|---|---|
| GF(256) + Reed–Solomon encode / error-and-erasure decode | done, fuzzed up to the theoretical limit |
| QR encoder (v1–40, L/M/Q/H, optimal segmentation, mask choice, PNG/SVG/text) | done, byte-identical to `segno` on 147 random symbols; readable by OpenCV |
| Matrix decoder (BCH format recovery, RS correction, segment parsing) | done |
| Image scanner (adaptive threshold, finder detection, homography + alignment refinement) | done, handles rotation, perspective, mirror, blur, noise, uneven light |

```
go build -o qz ./cmd/qz
./qz encode -o hello.png "hello"      # make a code
./qz scan hello.png                   # read it back with full stats
```
Remaining phases add the adversarial review, stretch features (distortion bench, damage tool, HTML explorer, multi-code), verification and final docs.
