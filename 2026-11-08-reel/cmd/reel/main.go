// Command reel is the command-line front end of the Reel video codec.
package main

import (
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"reel/codec"
)

const usage = `reel — a from-scratch hybrid video codec

usage:
  reel gen   -preset pan|objects|mixed|cut|noise|zoom [-w 176 -h 144 -n 30 -seed 1] -o out.y4m
  reel enc   -i in.y4m -o out.reel [-qp 28 -gop 30 -b 0 -range 16 -search diamond|full
                                    -subpel 2 -deblock=true -effort 1 -scenecut=true -bitrate 0]
  reel dec   -i in.reel -o out.y4m
  reel psnr  ref.y4m test.y4m
  reel info  in.reel
  reel report [-o report.html] [-quick]
`

func fatal(format string, a ...any) {
	msg := strings.TrimPrefix(fmt.Sprintf(format, a...), "reel: ") // codec errors already carry the prefix
	fmt.Fprintf(os.Stderr, "reel: %s\n", msg)
	os.Exit(1)
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprint(os.Stderr, usage)
		os.Exit(2)
	}
	cmd, args := os.Args[1], os.Args[2:]
	switch cmd {
	case "gen":
		cmdGen(args)
	case "enc":
		cmdEnc(args)
	case "dec":
		cmdDec(args)
	case "psnr":
		cmdPSNR(args)
	case "info":
		cmdInfo(args)
	case "report":
		cmdReport(args)
	case "-h", "--help", "help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "reel: unknown command %q\n\n%s", cmd, usage)
		os.Exit(2)
	}
}

func parse(fs *flag.FlagSet, args []string) {
	fs.SetOutput(os.Stderr)
	if err := fs.Parse(args); err != nil {
		os.Exit(2)
	}
}

func readVideo(path string) *codec.Video {
	f, err := os.Open(path)
	if err != nil {
		fatal("%v", err)
	}
	defer f.Close()
	v, err := codec.ReadY4M(f)
	if err != nil {
		fatal("%s: %v", path, err)
	}
	return v
}

func writeVideo(path string, v *codec.Video) {
	f, err := os.Create(path)
	if err != nil {
		fatal("%v", err)
	}
	if err := codec.WriteY4M(f, v); err != nil {
		fatal("%v", err)
	}
	if err := f.Close(); err != nil {
		fatal("%v", err)
	}
}

func cmdGen(args []string) {
	fs := flag.NewFlagSet("gen", flag.ExitOnError)
	g := codec.GenParams{}
	fs.StringVar(&g.Preset, "preset", "mixed", "pan|objects|mixed|cut|noise|zoom")
	fs.IntVar(&g.W, "w", 176, "width")
	fs.IntVar(&g.H, "h", 144, "height")
	fs.IntVar(&g.N, "n", 30, "frames")
	seed := fs.Uint("seed", 1, "seed")
	out := fs.String("o", "", "output .y4m")
	parse(fs, args)
	if *out == "" {
		fatal("gen: -o is required")
	}
	g.Seed = uint32(*seed)
	v, err := codec.Generate(g)
	if err != nil {
		fatal("%v", err)
	}
	writeVideo(*out, v)
	fmt.Printf("wrote %s: %dx%d, %d frames (%s)\n", *out, v.Width, v.Height, len(v.Frames), g.Preset)
}

func cmdEnc(args []string) {
	fs := flag.NewFlagSet("enc", flag.ExitOnError)
	p := codec.DefaultParams()
	in := fs.String("i", "", "input .y4m")
	out := fs.String("o", "", "output .reel")
	fs.IntVar(&p.QP, "qp", p.QP, "quantiser 0..51")
	fs.IntVar(&p.GOP, "gop", p.GOP, "I-frame interval")
	fs.IntVar(&p.BFrames, "b", p.BFrames, "B-frames between anchors (0..4)")
	fs.IntVar(&p.Range, "range", p.Range, "search range in pixels (<=40)")
	search := fs.String("search", "diamond", "diamond|full")
	fs.IntVar(&p.SubPel, "subpel", p.SubPel, "0 integer, 1 half, 2 quarter")
	fs.BoolVar(&p.Deblock, "deblock", p.Deblock, "in-loop deblocking")
	fs.IntVar(&p.DbOffset, "dboffset", 0, "deblocking strength offset")
	fs.IntVar(&p.Effort, "effort", p.Effort, "0 fast, 1 full RDO")
	fs.BoolVar(&p.SceneCut, "scenecut", p.SceneCut, "insert I-frames at scene cuts")
	fs.IntVar(&p.Bitrate, "bitrate", 0, "target kbit/s (0 = constant QP)")
	parse(fs, args)
	if *in == "" || *out == "" {
		fatal("enc: -i and -o are required")
	}
	switch strings.ToLower(*search) {
	case "diamond":
		p.Search = codec.SearchDiamond
	case "full":
		p.Search = codec.SearchFull
	default:
		fatal("enc: unknown -search %q", *search)
	}
	v := readVideo(*in)
	t0 := time.Now()
	r, err := codec.Encode(v, p)
	if err != nil {
		fatal("%v", err)
	}
	if err := os.WriteFile(*out, r.Stream, 0o644); err != nil {
		fatal("%v", err)
	}
	rec := &codec.Video{Width: v.Width, Height: v.Height, FPSNum: v.FPSNum, FPSDen: v.FPSDen, Frames: r.Recon}
	m, _ := codec.Compare(v, rec)
	kbps := float64(r.Bytes) * 8 / (float64(len(v.Frames)) / v.FPS()) / 1000
	raw := len(v.Frames) * (v.Width*v.Height + 2*((v.Width+1)/2)*((v.Height+1)/2))
	fmt.Printf("encoded %d frames %dx%d in %.2fs\n", len(v.Frames), v.Width, v.Height, time.Since(t0).Seconds())
	fmt.Printf("  size      %d bytes  (%.1f kbit/s, %.1f:1 vs raw)\n", r.Bytes, kbps, float64(raw)/float64(r.Bytes))
	fmt.Printf("  quality   PSNR %.2f dB (Y %.2f U %.2f V %.2f)  SSIM %.4f\n", m.PSNR, m.PSNRY, m.PSNRU, m.PSNRV, m.SSIM)
	fmt.Printf("  search    %d SAD evaluations\n", r.SADEvals)
	if p.Bitrate > 0 {
		switch {
		case kbps > 1.15*float64(p.Bitrate):
			fmt.Printf("  warning   target %d kbit/s is below what this content needs even at QP %d; got %.1f kbit/s\n", p.Bitrate, codec.MaxQP, kbps)
		case kbps < 0.85*float64(p.Bitrate):
			fmt.Printf("  note      the quantiser floor (QP 0) was reached; used only %.1f of the %d kbit/s target\n", kbps, p.Bitrate)
		}
	}
}

func cmdDec(args []string) {
	fs := flag.NewFlagSet("dec", flag.ExitOnError)
	in := fs.String("i", "", "input .reel")
	out := fs.String("o", "", "output .y4m")
	parse(fs, args)
	if *in == "" || *out == "" {
		fatal("dec: -i and -o are required")
	}
	data, err := os.ReadFile(*in)
	if err != nil {
		fatal("%v", err)
	}
	v, _, err := codec.Decode(data)
	if err != nil {
		fatal("%v", err)
	}
	writeVideo(*out, v)
	fmt.Printf("decoded %d frames %dx%d -> %s\n", len(v.Frames), v.Width, v.Height, *out)
}

func cmdPSNR(args []string) {
	if len(args) != 2 {
		fatal("psnr: need two .y4m files")
	}
	a, b := readVideo(args[0]), readVideo(args[1])
	m, err := codec.Compare(a, b)
	if err != nil {
		fatal("%v", err)
	}
	if len(a.Frames) != len(b.Frames) {
		fmt.Fprintf(os.Stderr, "warning: %d vs %d frames, comparing the first %d\n", len(a.Frames), len(b.Frames), m.Frames)
	}
	fmt.Printf("PSNR %.3f dB  (Y %.3f  U %.3f  V %.3f)  worst-frame %.2f dB  SSIM %.5f  over %d frames\n",
		m.PSNR, m.PSNRY, m.PSNRU, m.PSNRV, m.Min, m.SSIM, m.Frames)
}

func cmdInfo(args []string) {
	if len(args) != 1 {
		fatal("info: need one .reel file")
	}
	data, err := os.ReadFile(args[0])
	if err != nil {
		fatal("%v", err)
	}
	v, st, err := codec.Decode(data)
	if err != nil {
		fatal("%v", err)
	}
	fmt.Printf("%s: %dx%d  %d frames  %.2f fps  %d bytes\n", args[0], v.Width, v.Height, len(v.Frames), v.FPS(), len(data))
	fmt.Println("  #  disp type  qp    bytes  skip intra  16x16 split   L0  L1  Bi  dbk")
	names := []string{"I", "P", "B"}
	for i, s := range st {
		fmt.Printf("%3d %5d  %s   %3d %8d %5d %5d %6d %5d %4d %3d %3d  %v\n", i, s.Disp, names[s.Type], s.QP, s.Bytes,
			s.Skip, s.Intra, s.Inter16, s.InterSplit, s.L0, s.L1, s.Bi, s.Deblock)
	}
}
