# Landmark

Shazam-style audio fingerprinting from scratch in Go (stdlib only).

*Status: Phase 4 complete — all three stretch features shipped (speed-tolerant search, DJ-mix timeline, HTML visualizer) plus polish; verification next.*

```
go build -o landmark ./cmd/landmark
./landmark synth -n 12 -out corpus          # compose 12 procedural songs
./landmark index -out lib.lmk corpus        # fingerprint them
./landmark degrade -in corpus/song0003.wav -start 20 -len 8 -snr 0 -out q.wav
./landmark identify -db lib.lmk q.wav       # -> song0003, starts at 20.00 s
./landmark eval                             # robustness benchmark
./landmark mix -out mix.wav corpus/song0003.wav:5-30 corpus/song0001.wav:20-45
./landmark timeline -db lib.lmk mix.wav     # which song plays when
./landmark viz -db lib.lmk -out report.html q.wav
```

Implemented so far: WAV I/O + DSP (FFT/STFT/resampler), constellation + landmark hashing, persistent inverted
index with offset-histogram voting, procedural synthesizer + degradations + evaluation harness, speed-tolerant search.
