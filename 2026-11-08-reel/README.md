# Reel — a from-scratch hybrid video codec (Go)

Status: **Phase 2 (core build) complete** — see [PLAN.md](PLAN.md).

Reel is an H.264-style hybrid video codec written from scratch in Go (stdlib only): encoder, decoder,
`.reel` container, procedural test-video generator, PSNR/SSIM metrics.

## Working now (the four required features)
1. **Intra codec** — 4x4 integer DCT + quantiser, DC/V/H/TrueMotion intra prediction, zig-zag, context-adaptive binary range coding.
2. **Inter prediction** — P-frames, diamond/full motion search, quarter-pel (6-tap) luma / eighth-pel chroma compensation, median MV prediction, skip, 16x16/16x8/8x16/8x8 partitions.
3. **Closed-loop reconstruction** — decoder output is bit-identical to the encoder's own reference frames (`go test ./codec`).
4. **Measurement lab** — `reel gen` (seeded procedural clips), `reel psnr`, `reel info`.

(B-frames, the deblocking filter, rate control and RDO are also already in the code and being reviewed in Phase 3.)

```
go build -o reel ./cmd/reel
reel gen -preset mixed -n 30 -o clip.y4m
reel enc -i clip.y4m -o clip.reel -qp 28
reel dec -i clip.reel -o out.y4m
reel psnr clip.y4m out.y4m
reel info clip.reel
```
