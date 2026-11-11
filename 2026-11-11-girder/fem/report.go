package fem

import (
	"fmt"
	"html"
	"math"
	"strings"
)

const pageCSS = `
:root{--bg:#f6f5f1;--card:#fff;--ink:#1c2230;--mute:#667085;--line:#e2e0d8;--accent:#2457c5;--ok:#1e8e5a;--bad:#c0392b;--mesh:rgba(20,30,50,.28);--solid:#1c2230;--topobg:#ece9df;--moment:rgba(36,87,197,.18);--momentline:#2457c5}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#10141c;--card:#181e2a;--ink:#e8ebf2;--mute:#97a1b5;--line:#2a3345;--accent:#7aa2ff;--ok:#4cc38a;--bad:#ff7a6b;--mesh:rgba(255,255,255,.22);--solid:#dfe6f5;--topobg:#0d1118;--moment:rgba(122,162,255,.2);--momentline:#7aa2ff}}
:root[data-theme=dark]{--bg:#10141c;--card:#181e2a;--ink:#e8ebf2;--mute:#97a1b5;--line:#2a3345;--accent:#7aa2ff;--ok:#4cc38a;--bad:#ff7a6b;--mesh:rgba(255,255,255,.22);--solid:#dfe6f5;--topobg:#0d1118;--moment:rgba(122,162,255,.2);--momentline:#7aa2ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:28px;letter-spacing:-.02em;margin:0 0 4px}h2{font-size:18px;margin:34px 0 10px;letter-spacing:-.01em}
.sub{color:var(--mute);margin:0 0 22px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
.stat b{display:block;font-size:20px;font-variant-numeric:tabular-nums;letter-spacing:-.01em}.stat span{color:var(--mute);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.panels{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr));gap:14px}
figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
figcaption{font-weight:600;margin:0 0 6px}figcaption small{display:block;color:var(--mute);font-weight:400}
svg{width:100%;height:auto;display:block}.tick{fill:var(--mute);font-size:11px;font-variant-numeric:tabular-nums}
.meshlines polygon{stroke:var(--mesh);stroke-width:.5}.outline line{stroke:var(--ink);stroke-width:.8;stroke-dasharray:3 3;opacity:.55}
.undef{stroke:var(--mute);stroke-width:1.4;stroke-dasharray:4 4;opacity:.7}.def{fill:none;stroke-width:3.2;stroke-linecap:round;stroke-linejoin:round}.node{fill:var(--ink)}.support{fill:var(--bad);opacity:.8}
.moment{fill:var(--moment);stroke:var(--momentline);stroke-width:1.2}
.topobg{fill:var(--topobg)}.solid{fill:var(--solid)}
table{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-variant-numeric:tabular-nums}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--line);font-size:14px}th{color:var(--mute);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}tr:last-child td{border-bottom:0}
.pass{color:var(--ok);font-weight:700}.fail{color:var(--bad);font-weight:700}
.tablewrap{overflow-x:auto}code{font:13px ui-monospace,Menlo,Consolas,monospace;background:var(--card);border:1px solid var(--line);padding:1px 5px;border-radius:5px}
@media(max-width:560px){h1{font-size:23px}}
`

// Page wraps body HTML in the shared report shell.
func Page(title, subtitle, body string) string {
	return fmt.Sprintf(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>%s</title><style>%s</style></head><body><main><h1>%s</h1><p class="sub">%s</p>%s</main></body></html>`,
		html.EscapeString(title), pageCSS, html.EscapeString(title), html.EscapeString(subtitle), body)
}

func stat(label, val string) string {
	return fmt.Sprintf(`<div class="stat"><b>%s</b><span>%s</span></div>`, html.EscapeString(val), html.EscapeString(label))
}

var fieldMeta = map[Field][2]string{
	FieldVonMises: {"von Mises stress", "σ_vm"}, FieldSXX: {"Normal stress σxx", "σxx"}, FieldSYY: {"Normal stress σyy", "σyy"},
	FieldSXY: {"Shear stress τxy", "τxy"}, FieldS1: {"Max principal stress σ1", "σ1"}, FieldS3: {"Min principal stress σ3", "σ3"},
	FieldDispMag: {"Displacement magnitude", "|u|"}, FieldUX: {"Displacement ux", "ux"}, FieldUY: {"Displacement uy", "uy"},
}

// SolidReport renders a full HTML report for a solved solid model.
func SolidReport(in *Input, res *Results) (string, error) {
	md := res.Model
	m := md.Mesh
	scale := in.Scale
	if scale == 0 {
		scale = AutoDeformScale(m, res.Sol.U)
	}
	vm, _ := res.NodalField(FieldVonMises)
	vmax, at := MaxField(vm)
	disp, _ := res.NodalField(FieldDispMag)
	dmax, _ := MaxField(disp)
	var body strings.Builder
	body.WriteString(`<div class="grid">`)
	body.WriteString(stat("nodes / elements", fmt.Sprintf("%d / %d %s", m.NumNodes(), m.NumElems(), m.Type)))
	body.WriteString(stat("free DOFs", fmt.Sprint(res.Sol.Info.FreeDOFs)))
	body.WriteString(stat("max von Mises", fmtNum(vmax)))
	body.WriteString(stat("max |u|", fmtNum(dmax)))
	body.WriteString(stat("strain energy", fmtNum(res.Energy)))
	body.WriteString(stat("solver", string(res.Sol.Info.Solver)))
	body.WriteString(`</div>`)
	body.WriteString(`<div class="panels">`)
	for _, f := range in.Fields {
		vals, err := res.NodalField(f)
		if err != nil {
			return "", err
		}
		meta := fieldMeta[f]
		svg := ContourSVG(m, res.Sol.U, vals, ContourOpts{DeformScale: scale, ShowMesh: in.Mesh, Title: meta[0], Unit: meta[1]})
		fmt.Fprintf(&body, `<figure><figcaption>%s<small>deformed shape ×%s; dashed = undeformed outline</small></figcaption>%s</figure>`, meta[0], fmtNum(scale), svg)
	}
	body.WriteString(`</div><h2>Diagnostics</h2><div class="tablewrap"><table>`)
	row := func(k, v string) {
		fmt.Fprintf(&body, `<tr><th>%s</th><td>%s</td></tr>`, html.EscapeString(k), html.EscapeString(v))
	}
	row("Peak von Mises at node", fmt.Sprintf("%d  (x=%.4g, y=%.4g)", at, m.X[at], m.Y[at]))
	row("Plane condition", map[bool]string{true: "plane strain", false: "plane stress"}[md.Mat.PlaneStrain])
	row("Global force balance", fmt.Sprintf("Σ(F+R)x = %.2e, Σ(F+R)y = %.2e", res.Equilib[0], res.Equilib[1]))
	row("Strain energy ½uᵀKu", fmt.Sprintf("%.6g", res.Energy))
	row("External work ½Σf·u", fmt.Sprintf("%.6g", res.Sol.Compl))
	if res.Sol.Info.Solver == SolverDirect {
		row("Bandwidth (RCM)", fmt.Sprintf("%d → %d", res.Sol.Info.Bandwidth0, res.Sol.Info.Bandwidth1))
	} else {
		row("CG iterations", fmt.Sprintf("%d (residual %.1e)", res.Sol.Info.CG.Iters, res.Sol.Info.CG.Residual))
	}
	body.WriteString(`</table></div>`)
	title := in.Title
	if title == "" {
		title = "Girder solid analysis"
	}
	return Page(title, "Girder FEM report — linear elastic, small strain", body.String()), nil
}

// FrameReport renders a frame result page.
func FrameReport(in *Input, sol *FrameSolution) string {
	f := in.Frame
	var body strings.Builder
	maxU, maxM, maxN := 0.0, 0.0, 0.0
	for n := range f.X {
		maxU = math.Max(maxU, math.Hypot(sol.U[3*n], sol.U[3*n+1]))
	}
	for i, m := range f.Members {
		maxN = math.Max(maxN, math.Abs(f.AxialForce(sol, i)))
		if !m.Truss {
			L := f.length(m)
			for k := 0; k <= 20; k++ {
				maxM = math.Max(maxM, math.Abs(f.MomentAt(sol, i, L*float64(k)/20)))
			}
		}
	}
	scale := in.Scale
	if scale == 0 && maxU > 0 {
		x0, x1, y0, y1 := math.Inf(1), math.Inf(-1), math.Inf(1), math.Inf(-1)
		for i := range f.X {
			x0, x1, y0, y1 = math.Min(x0, f.X[i]), math.Max(x1, f.X[i]), math.Min(y0, f.Y[i]), math.Max(y1, f.Y[i])
		}
		scale = 0.08 * math.Max(x1-x0, y1-y0) / maxU
	}
	body.WriteString(`<div class="grid">`)
	body.WriteString(stat("nodes / members", fmt.Sprintf("%d / %d", len(f.X), len(f.Members))))
	body.WriteString(stat("max |u|", fmtNum(maxU)))
	body.WriteString(stat("max |moment|", fmtNum(maxM)))
	body.WriteString(stat("max |axial|", fmtNum(maxN)))
	body.WriteString(`</div><div class="panels">`)
	fmt.Fprintf(&body, `<figure><figcaption>Deformed shape and bending moment<small>deformation ×%s; colour = axial force (blue compression → red tension); shaded = moment diagram on the tension side</small></figcaption>%s</figure>`, fmtNum(scale), FrameSVG(f, sol, scale, 720, true))
	anyBeam := false
	for _, m := range f.Members {
		anyBeam = anyBeam || !m.Truss
	}
	body.WriteString(`</div><h2>Member forces</h2><div class="tablewrap"><table><tr><th>#</th><th>nodes</th><th>N (tension +)</th>`)
	if anyBeam {
		body.WriteString(`<th>V start</th><th>M start</th><th>M end</th>`)
	}
	body.WriteString(`</tr>`)
	for i, m := range f.Members {
		ef := sol.EndForces[i]
		fmt.Fprintf(&body, `<tr><td>%d</td><td>%d–%d %s</td><td>%.5g</td>`, i, m.N1, m.N2, map[bool]string{true: "bar", false: "beam"}[m.Truss], f.AxialForce(sol, i))
		if anyBeam {
			if m.Truss {
				body.WriteString(`<td>–</td><td>–</td><td>–</td>`)
			} else {
				fmt.Fprintf(&body, `<td>%.5g</td><td>%.5g</td><td>%.5g</td>`, ef[1], ef[2], ef[5])
			}
		}
		body.WriteString(`</tr>`)
	}
	body.WriteString(`</table></div><h2>Reactions</h2><div class="tablewrap"><table><tr><th>node</th><th>Rx</th><th>Ry</th><th>Mz</th></tr>`)
	for n := range f.X {
		rx, ry, rm := sol.R[3*n], sol.R[3*n+1], sol.R[3*n+2]
		rmax := 0.0
		for _, v := range sol.R {
			rmax = math.Max(rmax, math.Abs(v))
		}
		for _, p := range []*float64{&rx, &ry, &rm} { // suppress round-off noise
			if math.Abs(*p) < 1e-10*rmax {
				*p = 0
			}
		}
		if math.Abs(rx)+math.Abs(ry)+math.Abs(rm) > 0 {
			fmt.Fprintf(&body, `<tr><td>%d</td><td>%.5g</td><td>%.5g</td><td>%.5g</td></tr>`, n, rx, ry, rm)
		}
	}
	body.WriteString(`</table></div>`)
	title := in.Title
	if title == "" {
		title = "Girder frame analysis"
	}
	return Page(title, "Girder FEM report — 2-D Euler–Bernoulli frame/truss", body.String())
}
