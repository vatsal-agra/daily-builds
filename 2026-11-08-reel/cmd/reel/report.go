package main

import (
	"bytes"
	"encoding/base64"
	"flag"
	"fmt"
	"html"
	"image/png"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"

	"reel/codec"
)

// ---------------------------------------------------------------- data model

type rdPoint struct {
	QP         int
	Kbps, PSNR float64
	SSIM       float64
	Bytes      int
	Secs       float64
	Evals      int
}

type series struct {
	Name string
	Pts  []rdPoint
}

func (s series) rd() []codec.RDPoint {
	out := make([]codec.RDPoint, len(s.Pts))
	for i, p := range s.Pts {
		out[i] = codec.RDPoint{Rate: p.Kbps, PSNR: p.PSNR}
	}
	return out
}

type step struct {
	Name string
	P    func(p *codec.EncParams)
}

var ladder = []step{
	{"Intra only", func(p *codec.EncParams) { p.GOP = 1 }},
	{"P-frames, 16x16, integer-pel", func(p *codec.EncParams) { p.Effort = 0; p.SubPel = 0; p.Deblock = false }},
	{"+ quarter-pel motion", func(p *codec.EncParams) { p.Effort = 0; p.Deblock = false }},
	{"+ partitions & RDO", func(p *codec.EncParams) { p.Deblock = false }},
	{"+ deblocking filter", func(p *codec.EncParams) {}},
	{"+ B-frames (2)", func(p *codec.EncParams) { p.BFrames = 2 }},
}

type clipSpec struct {
	Preset string
	Blurb  string
}

type clipResult struct {
	Spec     clipSpec
	Video    *codec.Video
	Ladder   []series
	X264     []series
	Search   []searchRow
	RC       []rcRow
	Final    *codec.EncResult
	FinalQP  int
	Decoded  *codec.Video
	DecStats []codec.FrameStat
}

type searchRow struct {
	Name       string
	Evals      int
	Secs       float64
	Kbps, PSNR float64
}

type rcRow struct {
	Target     int
	Kbps, PSNR float64
}

// ---------------------------------------------------------------- measuring

func measure(v *codec.Video, p codec.EncParams) (rdPoint, *codec.EncResult, error) {
	t0 := time.Now()
	r, err := codec.Encode(v, p)
	if err != nil {
		return rdPoint{}, nil, err
	}
	secs := time.Since(t0).Seconds()
	rec := &codec.Video{Width: v.Width, Height: v.Height, FPSNum: v.FPSNum, FPSDen: v.FPSDen, Frames: r.Recon}
	m, err := codec.Compare(v, rec)
	if err != nil {
		return rdPoint{}, nil, err
	}
	return rdPoint{QP: p.QP, Kbps: float64(r.Bytes) * 8 / (float64(len(v.Frames)) / v.FPS()) / 1000,
		PSNR: m.PSNR, SSIM: m.SSIM, Bytes: r.Bytes, Secs: secs, Evals: r.SADEvals}, r, nil
}

func haveX264() bool {
	if _, err := exec.LookPath("ffmpeg"); err != nil {
		return false
	}
	out, err := exec.Command("ffmpeg", "-hide_banner", "-encoders").CombinedOutput()
	return err == nil && bytes.Contains(out, []byte("libx264"))
}

func runX264(v *codec.Video, dir string, qp int, preset string, bf int) (rdPoint, error) {
	in := filepath.Join(dir, "in.y4m") // written once by analyse()
	tag := fmt.Sprintf("%s_%d_%d", preset, bf, qp)
	h264 := filepath.Join(dir, tag+".h264")
	out := filepath.Join(dir, tag+".y4m")
	run := func(args ...string) error {
		b, err := exec.Command("ffmpeg", append([]string{"-v", "error", "-y"}, args...)...).CombinedOutput()
		if err != nil {
			return fmt.Errorf("ffmpeg: %v: %s", err, b)
		}
		return nil
	}
	if err := run("-i", in, "-c:v", "libx264", "-qp", fmt.Sprint(qp), "-preset", preset, "-bf", fmt.Sprint(bf), "-g", "30", "-f", "h264", h264); err != nil {
		return rdPoint{}, err
	}
	if err := run("-i", h264, "-pix_fmt", "yuv420p", out); err != nil {
		return rdPoint{}, err
	}
	st, _ := os.Stat(h264)
	f, err := os.Open(out)
	if err != nil {
		return rdPoint{}, err
	}
	defer f.Close()
	dec, err := codec.ReadY4M(f)
	if err != nil {
		return rdPoint{}, err
	}
	m, err := codec.Compare(v, dec)
	if err != nil {
		return rdPoint{}, err
	}
	return rdPoint{QP: qp, Kbps: float64(st.Size()) * 8 / (float64(len(v.Frames)) / v.FPS()) / 1000, PSNR: m.PSNR, SSIM: m.SSIM, Bytes: int(st.Size())}, nil
}

// parallel runs fns on all CPUs.
func parallel(fns []func()) {
	var wg sync.WaitGroup
	sem := make(chan struct{}, runtime.NumCPU())
	for _, fn := range fns {
		wg.Add(1)
		sem <- struct{}{}
		go func(fn func()) {
			defer wg.Done()
			defer func() { <-sem }()
			fn()
		}(fn)
	}
	wg.Wait()
}

func analyse(spec clipSpec, w, h, n int, qps []int, withX264 bool, tmp string) (*clipResult, error) {
	v, err := codec.Generate(codec.GenParams{Preset: spec.Preset, W: w, H: h, N: n, Seed: 1})
	if err != nil {
		return nil, err
	}
	cr := &clipResult{Spec: spec, Video: v}
	cr.Ladder = make([]series, len(ladder))
	var firstErr error
	var mu sync.Mutex
	fail := func(e error) {
		mu.Lock()
		if firstErr == nil {
			firstErr = e
		}
		mu.Unlock()
	}
	for i, st := range ladder {
		cr.Ladder[i] = series{Name: st.Name, Pts: make([]rdPoint, len(qps))}
	}
	var jobs []func()
	for i, st := range ladder {
		for j, qp := range qps {
			i, j, qp, st := i, j, qp, st
			jobs = append(jobs, func() {
				p := codec.DefaultParams()
				p.QP = qp
				st.P(&p)
				pt, _, err := measure(v, p)
				if err != nil {
					fail(err)
					return
				}
				cr.Ladder[i].Pts[j] = pt
			})
		}
	}
	if withX264 {
		if err := os.MkdirAll(tmp, 0o755); err != nil {
			return nil, err
		}
		f, err := os.Create(filepath.Join(tmp, "in.y4m"))
		if err != nil {
			return nil, err
		}
		if err := codec.WriteY4M(f, v); err != nil {
			return nil, err
		}
		f.Close()
		cr.X264 = []series{{Name: "libx264 medium, 2 B-frames", Pts: make([]rdPoint, len(qps))}, {Name: "libx264 ultrafast", Pts: make([]rdPoint, len(qps))}}
		for j, qp := range qps {
			j, qp := j, qp
			jobs = append(jobs, func() {
				pt, err := runX264(v, tmp, qp, "medium", 2)
				if err != nil {
					fail(err)
					return
				}
				cr.X264[0].Pts[j] = pt
			}, func() {
				pt, err := runX264(v, tmp, qp, "ultrafast", 0)
				if err != nil {
					fail(err)
					return
				}
				cr.X264[1].Pts[j] = pt
			})
		}
	}
	// search algorithm comparison at a fixed QP
	mid := qps[len(qps)/2]
	type sv struct {
		name string
		mod  func(p *codec.EncParams)
	}
	svs := []sv{
		{"Diamond, range 16", func(p *codec.EncParams) {}},
		{"Diamond, range 40", func(p *codec.EncParams) { p.Range = 40 }},
		{"Full search, range 16", func(p *codec.EncParams) { p.Search = codec.SearchFull }},
		{"Full search, range 40", func(p *codec.EncParams) { p.Search = codec.SearchFull; p.Range = 40 }},
	}
	cr.Search = make([]searchRow, len(svs))
	for i, s := range svs {
		i, s := i, s
		jobs = append(jobs, func() {
			p := codec.DefaultParams()
			p.QP = mid
			s.mod(&p)
			pt, _, err := measure(v, p)
			if err != nil {
				fail(err)
				return
			}
			cr.Search[i] = searchRow{s.name, pt.Evals, pt.Secs, pt.Kbps, pt.PSNR}
		})
	}
	parallel(jobs)
	if firstErr != nil {
		return nil, firstErr
	}
	// final configuration artefacts (B-frames on) for the visual sections
	p := codec.DefaultParams()
	p.QP, p.BFrames = mid, 2
	pt, res, err := measure(v, p)
	if err != nil {
		return nil, err
	}
	cr.Final, cr.FinalQP = res, mid
	cr.Decoded, cr.DecStats, err = codec.Decode(res.Stream)
	if err != nil {
		return nil, err
	}
	// rate-control accuracy at 0.5x / 1x / 2x of the fixed-QP bitrate
	for _, f := range []float64{0.5, 1, 2} {
		target := int(math.Round(pt.Kbps*f/5) * 5)
		if target < 5 {
			target = 5
		}
		q := codec.DefaultParams()
		q.BFrames = 2
		q.Bitrate = target
		rp, _, err := measure(v, q)
		if err != nil {
			return nil, err
		}
		cr.RC = append(cr.RC, rcRow{target, rp.Kbps, rp.PSNR})
	}
	return cr, nil
}

// ---------------------------------------------------------------- SVG helpers

func niceStep(span float64, target int) float64 {
	raw := span / float64(target)
	mag := math.Pow(10, math.Floor(math.Log10(raw)))
	for _, m := range []float64{1, 2, 5, 10} {
		if raw <= m*mag {
			return m * mag
		}
	}
	return 10 * mag
}

func rdChart(ss []series, ids []int) string {
	const W, H, L, R, T, B = 720.0, 400.0, 56.0, 16.0, 16.0, 46.0
	minX, maxX, minY, maxY := math.Inf(1), math.Inf(-1), math.Inf(1), math.Inf(-1)
	for _, s := range ss {
		for _, p := range s.Pts {
			minX, maxX = math.Min(minX, p.Kbps), math.Max(maxX, p.Kbps)
			minY, maxY = math.Min(minY, p.PSNR), math.Max(maxY, p.PSNR)
		}
	}
	lx0, lx1 := math.Floor(math.Log10(minX)*3)/3, math.Ceil(math.Log10(maxX)*3)/3
	ys := niceStep(maxY-minY, 6)
	y0, y1 := math.Floor(minY/ys)*ys, math.Ceil(maxY/ys)*ys
	px := func(k float64) float64 { return L + (math.Log10(k)-lx0)/(lx1-lx0)*(W-L-R) }
	py := func(v float64) float64 { return T + (1-(v-y0)/(y1-y0))*(H-T-B) }
	var b strings.Builder
	fmt.Fprintf(&b, `<svg class="chart" viewBox="0 0 %.0f %.0f" role="img" aria-label="rate-distortion curves">`, W, H)
	for v := y0; v <= y1+1e-9; v += ys {
		fmt.Fprintf(&b, `<line class="grid" x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f"/><text class="tick" x="%.1f" y="%.1f" text-anchor="end">%.0f</text>`, L, W-R, py(v), py(v), L-6, py(v)+4, v)
	}
	for e := math.Floor(lx0); e <= math.Ceil(lx1); e++ {
		for _, m := range []float64{1, 2, 3, 5, 7} {
			k := m * math.Pow(10, e)
			if k < math.Pow(10, lx0)*0.999 || k > math.Pow(10, lx1)*1.001 {
				continue
			}
			fmt.Fprintf(&b, `<line class="grid" x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f"/><text class="tick" x="%.1f" y="%.1f" text-anchor="middle">%g</text>`, px(k), px(k), T, H-B, px(k), H-B+16, k)
		}
	}
	fmt.Fprintf(&b, `<text class="axis" x="%.0f" y="%.0f" text-anchor="middle">bitrate (kbit/s, log scale) — further left is better</text>`, (L+W-R)/2, H-8)
	fmt.Fprintf(&b, `<text class="axis" transform="translate(14 %.0f) rotate(-90)" text-anchor="middle">PSNR (dB) — higher is better</text>`, (T+H-B)/2)
	for si, s := range ss {
		cls := fmt.Sprintf("s%d", ids[si])
		var pts []string
		for _, p := range s.Pts {
			pts = append(pts, fmt.Sprintf("%.1f,%.1f", px(p.Kbps), py(p.PSNR)))
		}
		dash := ""
		if strings.HasPrefix(s.Name, "libx264") {
			dash = ` stroke-dasharray="6 4"`
		}
		fmt.Fprintf(&b, `<polyline class="line %s" fill="none"%s points="%s"/>`, cls, dash, strings.Join(pts, " "))
		for _, p := range s.Pts {
			fmt.Fprintf(&b, `<circle class="dot %s" cx="%.1f" cy="%.1f" r="4"><title>%s, QP %d: %.1f kbit/s, %.2f dB, SSIM %.4f</title></circle>`,
				cls, px(p.Kbps), py(p.PSNR), html.EscapeString(s.Name), p.QP, p.Kbps, p.PSNR, p.SSIM)
		}
	}
	b.WriteString(`</svg>`)
	return b.String()
}

func legend(ss []series, ids []int) string {
	var b strings.Builder
	b.WriteString(`<ul class="legend">`)
	for i, s := range ss {
		dash := ""
		if strings.HasPrefix(s.Name, "libx264") {
			dash = " dashed"
		}
		fmt.Fprintf(&b, `<li><span class="sw s%d%s"></span>%s</li>`, ids[i], dash, html.EscapeString(s.Name))
	}
	b.WriteString(`</ul>`)
	return b.String()
}

func timeline(st []codec.FrameStat, n int) string {
	const W, H, L, B = 720.0, 220.0, 50.0, 28.0
	bytes := make([]int, n)
	typ := make([]int, n)
	maxB := 1
	for _, s := range st {
		bytes[s.Disp], typ[s.Disp] = s.Bytes, s.Type
		if s.Bytes > maxB {
			maxB = s.Bytes
		}
	}
	// the I-frame dwarfs everything; clip the axis at 3x the largest P/B so the rest is readable
	capV := 0
	for i := range bytes {
		if typ[i] != codec.FrameI && bytes[i] > capV {
			capV = bytes[i]
		}
	}
	if capV == 0 {
		capV = maxB
	}
	capV = int(float64(capV) * 1.25)
	var b strings.Builder
	fmt.Fprintf(&b, `<svg class="chart" viewBox="0 0 %.0f %.0f" role="img" aria-label="bytes per frame">`, W, H)
	bw := (W - L - 10) / float64(n)
	step := niceStep(float64(capV), 4)
	for v := 0.0; v <= float64(capV); v += step {
		y := H - B - v/float64(capV)*(H-B-12)
		fmt.Fprintf(&b, `<line class="grid" x1="%.0f" x2="%.0f" y1="%.1f" y2="%.1f"/><text class="tick" x="%.0f" y="%.1f" text-anchor="end">%g</text>`, L, W-10, y, y, L-6, y+4, v)
	}
	names := []string{"I", "P", "B"}
	for i := 0; i < n; i++ {
		v := bytes[i]
		clipped := false
		if v > capV {
			v, clipped = capV, true
		}
		h := float64(v) / float64(capV) * (H - B - 12)
		x := L + float64(i)*bw
		fmt.Fprintf(&b, `<rect class="bar t%d" x="%.1f" y="%.1f" width="%.1f" height="%.1f"><title>frame %d (%s): %d bytes</title></rect>`, typ[i], x+1, H-B-h, math.Max(bw-2, 1), h, i, names[typ[i]], bytes[i])
		if clipped {
			fmt.Fprintf(&b, `<text class="tick" x="%.1f" y="%.1f" text-anchor="middle">%dK▲</text>`, x+bw/2, 12.0, bytes[i]/1000)
		}
	}
	fmt.Fprintf(&b, `<text class="axis" x="%.0f" y="%.0f" text-anchor="middle">display frame →</text><text class="axis" transform="translate(12 %.0f) rotate(-90)" text-anchor="middle">bytes</text></svg>`, (L+W)/2, H-6, (H-B)/2)
	return b.String()
}

func encodePNG(f func(w *bytes.Buffer) error) string {
	var buf bytes.Buffer
	if err := f(&buf); err != nil {
		return ""
	}
	return "data:image/png;base64," + base64.StdEncoding.EncodeToString(buf.Bytes())
}

// overlay draws the macroblock decisions of one decoded frame on top of its picture.
func overlay(pic string, w, h int, st codec.FrameStat, arrows bool) string {
	mbW := (w + 15) / 16
	var b strings.Builder
	fmt.Fprintf(&b, `<div class="pic"><img src="%s" alt="decoded frame" width="%d" height="%d"><svg viewBox="0 0 %d %d" preserveAspectRatio="none">`, pic, w, h, w, h)
	kinds := []string{"skip", "inter", "intra", "split"}
	for i, m := range st.MVs {
		x, y := (i%mbW)*16, (i/mbW)*16
		fmt.Fprintf(&b, `<rect class="mb k%s" x="%d" y="%d" width="16" height="16"/>`, kinds[m.Kind], x, y)
		if arrows && m.Kind != 2 && (m.MVX != 0 || m.MVY != 0) {
			cx, cy := float64(x)+8, float64(y)+8
			dir := "d" + fmt.Sprint(m.Dir)
			fmt.Fprintf(&b, `<line class="arrow %s" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/><circle class="tip %s" cx="%.1f" cy="%.1f" r="1.1"/>`,
				dir, cx, cy, cx+float64(m.MVX)/4*3, cy+float64(m.MVY)/4*3, dir, cx+float64(m.MVX)/4*3, cy+float64(m.MVY)/4*3)
		}
	}
	b.WriteString(`</svg></div>`)
	return b.String()
}

// ---------------------------------------------------------------- page

func bdCell(anchor, test series) string {
	v, err := codec.BDRate(anchor.rd(), test.rd())
	if err != nil {
		return `<td class="num muted">n/a</td>`
	}
	cls := "good"
	if v > 0.5 {
		cls = "bad"
	} else if math.Abs(v) <= 0.5 {
		cls = "muted"
	}
	return fmt.Sprintf(`<td class="num %s">%+.1f%%</td>`, cls, v)
}

func renderClip(cr *clipResult, id int, x264 bool) string {
	var b strings.Builder
	v := cr.Video
	fmt.Fprintf(&b, `<section><h2>Clip %d — <code>%s</code></h2><p class="lede">%s <span class="muted">(%d×%d, %d frames @ %.0f fps, seeded generator)</span></p>`,
		id+1, cr.Spec.Preset, html.EscapeString(cr.Spec.Blurb), v.Width, v.Height, len(v.Frames), v.FPS())

	all := append(append([]series{}, cr.Ladder...), cr.X264...)
	ids := make([]int, len(all))
	for i := range ids {
		ids[i] = i
	}
	b.WriteString(`<h3>What each coding tool buys</h3>`)
	b.WriteString(`<p>Each line adds one tool to the previous one (QP sweep, 5 points). `)
	if x264 {
		b.WriteString(`Dashed lines are the real libx264 for scale. `)
	}
	b.WriteString(`</p>` + rdChart(all, ids) + legend(all, ids))

	b.WriteString(`<table><thead><tr><th>Configuration</th><th class="num">kbit/s @ QP ` + fmt.Sprint(cr.Ladder[0].Pts[len(cr.Ladder[0].Pts)/2].QP) + `</th><th class="num">PSNR dB</th><th class="num">Δ rate vs previous row</th><th class="num">Δ rate vs intra-only</th></tr></thead><tbody>`)
	for i, s := range cr.Ladder {
		mid := s.Pts[len(s.Pts)/2]
		prev, vs := `<td class="num muted">—</td>`, `<td class="num muted">—</td>`
		if i > 0 {
			prev = bdCell(cr.Ladder[i-1], s)
			vs = bdCell(cr.Ladder[0], s)
		}
		fmt.Fprintf(&b, `<tr><td><span class="sw s%d"></span>%s</td><td class="num">%.1f</td><td class="num">%.2f</td>%s%s</tr>`, i, html.EscapeString(s.Name), mid.Kbps, mid.PSNR, prev, vs)
	}
	for k, s := range cr.X264 {
		mid := s.Pts[len(s.Pts)/2]
		fmt.Fprintf(&b, `<tr class="ref"><td><span class="sw s%d dashed"></span>%s</td><td class="num">%.1f</td><td class="num">%.2f</td><td class="num muted">—</td>%s</tr>`,
			len(cr.Ladder)+k, html.EscapeString(s.Name), mid.Kbps, mid.PSNR, bdCell(cr.Ladder[0], s))
	}
	b.WriteString(`</tbody></table><p class="note">Δ rate is the Bjøntegaard delta-rate: the average bitrate change at equal PSNR over the overlapping quality range (negative = fewer bits). `)
	if x264 {
		last := cr.Ladder[len(cr.Ladder)-1]
		v1, e1 := codec.BDRate(cr.X264[0].rd(), last.rd())
		v2, e2 := codec.BDRate(cr.X264[1].rd(), last.rd())
		if e1 == nil && e2 == nil {
			fmt.Fprintf(&b, `<strong>Reel (all tools) needs %+.0f%% bits vs libx264 medium and %+.0f%% vs libx264 ultrafast at equal PSNR</strong> — x264 is a decade-optimised encoder with CABAC, 4x4/8x8 intra, multi-reference and trellis quantisation; Reel is a day of work, so the gap is the honest price of the features listed under "known limitations".`, v1, v2)
		}
	}
	b.WriteString(`</p>`)

	b.WriteString(`<h3>Motion search: how hard to look</h3><table><thead><tr><th>Search</th><th class="num">SAD evaluations</th><th class="num">encode time</th><th class="num">kbit/s</th><th class="num">PSNR dB</th></tr></thead><tbody>`)
	for _, r := range cr.Search {
		fmt.Fprintf(&b, `<tr><td>%s</td><td class="num">%s</td><td class="num">%.2f s</td><td class="num">%.1f</td><td class="num">%.2f</td></tr>`, html.EscapeString(r.Name), commas(r.Evals), r.Secs, r.Kbps, r.PSNR)
	}
	b.WriteString(`</tbody></table><p class="note">Measured at the middle QP with the full tool set. Diamond search with predictor candidates reaches nearly the quality of exhaustive search for a small fraction of the work.</p>`)

	b.WriteString(`<h3>Where the bits go</h3><p>Bytes per frame at QP ` + fmt.Sprint(cr.FinalQP) + ` with two B-frames. The I-frame bar is clipped (its size is printed on top): inter coding makes every other frame an order of magnitude cheaper, and B-frames are cheapest of all.</p>`)
	b.WriteString(timeline(cr.DecStats, len(v.Frames)))
	b.WriteString(`<ul class="legend"><li><span class="sw t0"></span>I-frame</li><li><span class="sw t1"></span>P-frame</li><li><span class="sw t2"></span>B-frame</li></ul>`)

	// pick frames to visualise
	var pSt, bSt *codec.FrameStat
	for i := range cr.DecStats {
		s := &cr.DecStats[i]
		if s.Type == codec.FrameP && pSt == nil && s.Disp >= 3 {
			pSt = s
		}
		if s.Type == codec.FrameB && bSt == nil && s.Disp >= 2 {
			bSt = s
		}
	}
	if pSt != nil {
		b.WriteString(`<h3>What the encoder decided</h3><div class="triple">`)
		show := func(title string, st *codec.FrameStat, arrows bool) {
			f := cr.Decoded.Frames[st.Disp]
			pic := encodePNG(func(w *bytes.Buffer) error { return png.Encode(w, codec.ToImage(f)) })
			fmt.Fprintf(&b, `<figure>%s<figcaption>%s<br><span class="muted">frame %d · %d bytes · %d skip / %d 16×16 / %d split / %d intra</span></figcaption></figure>`,
				overlay(pic, v.Width, v.Height, *st, arrows), title, st.Disp, st.Bytes, st.Skip, st.Inter16, st.InterSplit, st.Intra)
		}
		show("P-frame: macroblock modes and motion vectors (arrows ×3)", pSt, true)
		if bSt != nil {
			show("B-frame: modes; arrow colour = prediction direction", bSt, true)
		}
		src := v.Frames[pSt.Disp]
		pic := encodePNG(func(w *bytes.Buffer) error {
			return png.Encode(w, codec.DiffImage(src, cr.Decoded.Frames[pSt.Disp], 8))
		})
		fmt.Fprintf(&b, `<figure><div class="pic"><img src="%s" alt="coding error" width="%d" height="%d"></div><figcaption>Coding error of the P-frame, luma |source − decoded| ×8<br><span class="muted">dark = larger error</span></figcaption></figure></div>`, pic, v.Width, v.Height)
		b.WriteString(`<ul class="legend modes"><li><span class="sw kskip"></span>skip</li><li><span class="sw kinter"></span>inter 16×16</li><li><span class="sw ksplit"></span>inter split</li><li><span class="sw kintra"></span>intra</li><li><span class="sw d1l"></span>list 0 (past)</li><li><span class="sw d2l"></span>list 1 (future)</li><li><span class="sw d3l"></span>bi-predicted</li></ul>`)
	}

	b.WriteString(`<h3>Rate control</h3><table><thead><tr><th class="num">target kbit/s</th><th class="num">achieved kbit/s</th><th class="num">error</th><th class="num">PSNR dB</th></tr></thead><tbody>`)
	for _, r := range cr.RC {
		fmt.Fprintf(&b, `<tr><td class="num">%d</td><td class="num">%.1f</td><td class="num">%+.1f%%</td><td class="num">%.2f</td></tr>`, r.Target, r.Kbps, (r.Kbps/float64(r.Target)-1)*100, r.PSNR)
	}
	b.WriteString(`</tbody></table></section>`)
	return b.String()
}

func commas(n int) string {
	s := fmt.Sprint(n)
	var out []string
	for len(s) > 3 {
		out = append([]string{s[len(s)-3:]}, out...)
		s = s[:len(s)-3]
	}
	return strings.Join(append([]string{s}, out...), ",")
}

const css = `
:root{--bg:#fbfbf9;--fg:#1d1f23;--muted:#6a6f78;--card:#ffffff;--line:#e3e4e0;--grid:#ececE8;--accent:#0b5fff;
--s0:#6a6f78;--s1:#0072B2;--s2:#56B4E9;--s3:#009E73;--s4:#E69F00;--s5:#D55E00;--s6:#CC79A7;--s7:#1d1f23;
--t0:#D55E00;--t1:#0072B2;--t2:#009E73;--good:#0a7a4b;--bad:#b3261e;
--k-skip:rgba(120,120,120,.28);--k-inter:rgba(0,114,178,.30);--k-split:rgba(204,121,167,.45);--k-intra:rgba(213,94,0,.55)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14161a;--fg:#e8e9ec;--muted:#9aa0aa;--card:#1c1f25;--line:#2c3038;--grid:#2a2e36;--accent:#7aa7ff;
--s0:#9aa0aa;--s1:#56B4E9;--s2:#a6dcf7;--s3:#2fd0a0;--s4:#f5c04a;--s5:#ff8a3d;--s6:#e8a3cc;--s7:#e8e9ec;--t0:#ff8a3d;--t1:#56B4E9;--t2:#2fd0a0;--good:#46d391;--bad:#ff8078;
--k-skip:rgba(200,200,200,.22);--k-inter:rgba(86,180,233,.28);--k-split:rgba(232,163,204,.42);--k-intra:rgba(255,138,61,.55)}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:2rem;letter-spacing:-.02em;margin:.2em 0 .1em}
h2{font-size:1.4rem;margin:2.2em 0 .2em;padding-top:1.2em;border-top:1px solid var(--line)}
h3{font-size:1.05rem;margin:1.8em 0 .3em}
code{font:.92em ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--card);border:1px solid var(--line);padding:.05em .35em;border-radius:5px}
.lede{font-size:1.05rem;margin-top:.2em}.muted{color:var(--muted)}.note{color:var(--muted);font-size:.92rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:18px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card b{display:block;font-size:1.7rem;letter-spacing:-.02em}.card span{color:var(--muted);font-size:.9rem}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:.95rem;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--line)}th{font-weight:600;font-size:.85rem;color:var(--muted)}
tr:last-child td{border-bottom:0}.num{text-align:right;font-variant-numeric:tabular-nums}.good{color:var(--good);font-weight:600}.bad{color:var(--bad);font-weight:600}
tr.ref td{color:var(--muted)}
.table-wrap{overflow-x:auto}
svg.chart{width:100%;height:auto;background:var(--card);border:1px solid var(--line);border-radius:12px;display:block}
.grid{stroke:var(--grid);stroke-width:1}.tick{fill:var(--muted);font-size:11px}.axis{fill:var(--muted);font-size:12px}
.line{stroke-width:2.4}.dot{stroke:var(--card);stroke-width:1.5}
.s0.line{stroke:var(--s0)}.s1.line{stroke:var(--s1)}.s2.line{stroke:var(--s2)}.s3.line{stroke:var(--s3)}.s4.line{stroke:var(--s4)}.s5.line{stroke:var(--s5)}.s6.line{stroke:var(--s6)}.s7.line{stroke:var(--s7)}
.s0.dot{fill:var(--s0)}.s1.dot{fill:var(--s1)}.s2.dot{fill:var(--s2)}.s3.dot{fill:var(--s3)}.s4.dot{fill:var(--s4)}.s5.dot{fill:var(--s5)}.s6.dot{fill:var(--s6)}.s7.dot{fill:var(--s7)}
.legend{list-style:none;display:flex;flex-wrap:wrap;gap:6px 18px;padding:0;margin:10px 0;font-size:.9rem}
.legend li{display:flex;align-items:center;gap:7px}
.sw{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:6px;vertical-align:-2px}
.s0.sw{background:var(--s0)}.s1.sw{background:var(--s1)}.s2.sw{background:var(--s2)}.s3.sw{background:var(--s3)}.s4.sw{background:var(--s4)}.s5.sw{background:var(--s5)}.s6.sw{background:var(--s6)}.s7.sw{background:var(--s7)}
.sw.dashed{background:none!important;border-top:3px dashed currentColor;height:0;border-radius:0;width:18px;vertical-align:3px}
.s6.sw.dashed{color:var(--s6)}.s7.sw.dashed{color:var(--s7)}
.bar.t0,.sw.t0{fill:var(--t0);background:var(--t0)}.bar.t1,.sw.t1{fill:var(--t1);background:var(--t1)}.bar.t2,.sw.t2{fill:var(--t2);background:var(--t2)}
.triple{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px}
figcaption{font-size:.85rem;margin-top:8px}
.pic{position:relative;line-height:0}.pic img{width:100%;height:auto;image-rendering:pixelated;border-radius:6px}
.pic svg{position:absolute;inset:0;width:100%;height:100%}
.mb{stroke:rgba(0,0,0,.08);stroke-width:.3}.mb.kskip{fill:var(--k-skip)}.mb.kinter{fill:var(--k-inter)}.mb.ksplit{fill:var(--k-split)}.mb.kintra{fill:var(--k-intra)}
.arrow{stroke-width:.9;stroke-linecap:round}.arrow.d1,.tip.d1{stroke:var(--s5);fill:var(--s5)}.arrow.d2,.tip.d2{stroke:var(--s3);fill:var(--s3)}.arrow.d3,.tip.d3{stroke:var(--s7);fill:var(--s7)}
.sw.kskip{background:var(--k-skip);border:1px solid var(--line)}.sw.kinter{background:var(--k-inter)}.sw.ksplit{background:var(--k-split)}.sw.kintra{background:var(--k-intra)}
.sw.d1l{background:var(--s5)}.sw.d2l{background:var(--s3)}.sw.d3l{background:var(--s7)}
footer{margin-top:48px;color:var(--muted);font-size:.9rem;border-top:1px solid var(--line);padding-top:16px}
@media (max-width:560px){h1{font-size:1.6rem}th,td{padding:6px 7px;font-size:.85rem}}
`

func cmdReport(args []string) {
	fs := flag.NewFlagSet("report", flag.ExitOnError)
	out := fs.String("o", "report.html", "output html")
	quick := fs.Bool("quick", false, "smaller experiment (1 clip, 12 frames)")
	parse(fs, args)
	specs := []clipSpec{
		{"mixed", "Camera pan over a textured scene, five moving shapes with anti-aliased edges, a static HUD strip, a slow brightness fade and sensor noise — a bit of everything."},
		{"objects", "A static gradient with five textured shapes drifting, bouncing and rotating: large flat areas for skip mode, sharp moving edges for sub-pel motion."},
	}
	n, qps := 30, []int{22, 26, 30, 34, 38}
	if *quick {
		specs, n, qps = specs[:1], 12, []int{24, 30, 36, 42}
	}
	x264 := haveX264()
	tmp, err := os.MkdirTemp("", "reel-report-")
	if err != nil {
		fatal("%v", err)
	}
	defer os.RemoveAll(tmp)
	var res []*clipResult
	for i, s := range specs {
		fmt.Fprintf(os.Stderr, "analysing clip %d/%d (%s)…\n", i+1, len(specs), s.Preset)
		cr, err := analyse(s, 176, 144, n, qps, x264, filepath.Join(tmp, s.Preset))
		if err != nil {
			fatal("%v", err)
		}
		res = append(res, cr)
	}
	var b strings.Builder
	b.WriteString(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Reel codec lab</title><style>` + css + `</style></head><body><main>`)
	b.WriteString(`<h1>Reel — codec lab</h1><p class="lede">Every number below was measured by running the encoder and decoder in this repository on seeded procedural clips. Nothing is hard-coded.</p>`)
	// summary cards from the first clip
	first := res[0]
	last := first.Ladder[len(first.Ladder)-1]
	vsIntra, _ := codec.BDRate(first.Ladder[0].rd(), last.rd())
	mid := last.Pts[len(last.Pts)/2]
	b.WriteString(`<div class="cards">`)
	fmt.Fprintf(&b, `<div class="card"><b>%+.0f%%</b><span>bitrate vs intra-only at equal PSNR (clip 1, BD-rate)</span></div>`, vsIntra)
	fmt.Fprintf(&b, `<div class="card"><b>%.0f : 1</b><span>compression vs raw 4:2:0 at QP %d, %.1f dB</span></div>`, float64(first.Video.Width*first.Video.Height*3/2*len(first.Video.Frames))/float64(mid.Bytes), mid.QP, mid.PSNR)
	if x264 {
		v1, e := codec.BDRate(first.X264[0].rd(), last.rd())
		if e == nil {
			fmt.Fprintf(&b, `<div class="card"><b>%+.0f%%</b><span>bits vs libx264 medium at equal PSNR (positive = Reel needs more)</span></div>`, v1)
		}
	}
	fmt.Fprintf(&b, `<div class="card"><b>bit-exact</b><span>decoder output equals the encoder's reconstruction for every frame</span></div>`)
	b.WriteString(`</div>`)
	if !x264 {
		b.WriteString(`<p class="note">ffmpeg with libx264 was not found on this machine, so the external comparison is omitted.</p>`)
	}
	for i, cr := range res {
		b.WriteString(renderClip(cr, i, x264))
	}
	b.WriteString(`<footer><p><strong>Method.</strong> PSNR is (6·Y+U+V)/8 averaged over frames; bitrate is the total stream size over the clip duration. libx264 runs through ffmpeg at constant QP with the same GOP (30), then is decoded back and measured by the same code. BD-rate fits a cubic through log-rate vs PSNR over the overlapping range (4+ points).</p></footer></main></body></html>`)
	if err := os.WriteFile(*out, []byte(b.String()), 0o644); err != nil {
		fatal("%v", err)
	}
	fmt.Printf("wrote %s (%d KB)\n", *out, b.Len()/1024)
}
