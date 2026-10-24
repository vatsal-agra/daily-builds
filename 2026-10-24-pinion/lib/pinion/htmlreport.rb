# frozen_string_literal: true

require "cgi"
require "json"
require_relative "depgraph"

module Pinion
  # Self-contained HTML page: layered SVG dependency graph + status table.
  # Layout is computed here (BFS layers, barycentre ordering); the page's JS only handles
  # highlighting and filtering.
  module HtmlReport
    NODE_W = 196
    NODE_H = 46
    COL_GAP = 92
    ROW_GAP = 22
    PAD = 28

    module_function

    def render(manifest, registry, result)
      universe = result.universe
      solution = result.solution
      graph = DepGraph.new(manifest, universe, solution)
      names = [:root] + solution.keys.sort
      edges = names.flat_map { |n| graph.edges(n).map { |d, set| [n, d, set.to_s] } }
      depth = layers(names, edges)
      cols = order_columns(names, edges, depth)
      pos = place(cols)
      info = node_info(graph, universe, solution, manifest)
      width = PAD * 2 + cols.length * NODE_W + (cols.length - 1) * COL_GAP
      height = PAD * 2 + (cols.map(&:length).max || 1) * (NODE_H + ROW_GAP)
      page(manifest, graph, names, edges, pos, info, width, height, result)
    end

    # Shortest-path layer from the root (cycles and diamonds both fine).
    def layers(names, edges)
      depth = { root: 0 }
      queue = [:root]
      until queue.empty?
        n = queue.shift
        edges.each { |a, b, _| (depth[b] = depth[n] + 1; queue << b) if a == n && !depth.key?(b) }
      end
      names.each { |n| depth[n] ||= 1 }
      depth
    end

    def order_columns(names, edges, depth)
      cols = Array.new(depth.values.max + 1) { [] }
      names.each { |n| cols[depth[n]] << n }
      cols.each { |c| c.sort_by!(&:to_s) }
      rank = ->(col) { col.each_with_index.to_h }
      4.times do
        (1...cols.length).each do |i|
          r = rank.call(cols[i - 1])
          cols[i].sort_by! do |n|
            ps = edges.select { |_, b, _| b == n }.map { |a, _, _| r[a] }.compact
            [ps.empty? ? 1e9 : ps.sum.to_f / ps.length, n.to_s]
          end
        end
        (cols.length - 2).downto(0) do |i|
          r = rank.call(cols[i + 1])
          cols[i].sort_by! do |n|
            cs = edges.select { |a, _, _| a == n }.map { |_, b, _| r[b] }.compact
            [cs.empty? ? 1e9 : cs.sum.to_f / cs.length, n.to_s]
          end
        end
      end
      cols
    end

    def place(cols)
      tallest = cols.map(&:length).max || 1
      full = tallest * (NODE_H + ROW_GAP)
      pos = {}
      cols.each_with_index do |col, ci|
        offset = (full - col.length * (NODE_H + ROW_GAP)) / 2.0
        col.each_with_index do |n, ri|
          pos[n] = [PAD + ci * (NODE_W + COL_GAP), PAD + offset + ri * (NODE_H + ROW_GAP)]
        end
      end
      pos
    end

    def node_info(graph, universe, solution, manifest)
      info = {}
      info[:root] = { title: manifest.name, sub: "root", status: "root" }
      solution.each do |n, v|
        newer = universe.versions(n).select { |x| x > v }
        deps = graph.dependents(n)
        blockers = newer.empty? ? [] : deps.reject { |_, s| s.include?(newer.last) }.map { |d, s| "#{d == :root ? manifest.name : d} requires #{s}" }
        status = if newer.empty? then "latest"
                 elsif blockers.empty? then "behind"
                 else "held"
                 end
        info[n] = { title: n, sub: v.to_s, status: status, newest: newer.last&.to_s, blockers: blockers,
                    pre: v.prerelease?, yanked: universe.registry.entry(n, v).yanked }
      end
      info
    end

    def e(s) = CGI.escapeHTML(s.to_s)

    def page(manifest, graph, names, edges, pos, info, width, height, result)
      held = info.count { |k, i| k != :root && i[:status] == "held" }
      latest = info.count { |k, i| k != :root && i[:status] == "latest" }
      data = {
        edges: edges.map { |a, b, s| [a.to_s, b.to_s, s] },
        info: info.transform_keys(&:to_s).transform_values { |i| i.transform_keys(&:to_s) }
      }
      svg_edges = edges.map do |a, b, set|
        x1 = pos[a][0] + NODE_W
        y1 = pos[a][1] + NODE_H / 2.0
        x2 = pos[b][0]
        y2 = pos[b][1] + NODE_H / 2.0
        back = x2 <= x1
        dx = back ? 70 : (x2 - x1) * 0.5
        d = "M#{x1.round(1)},#{y1.round(1)} C#{(x1 + dx).round(1)},#{y1.round(1)} #{(x2 - dx).round(1)},#{y2.round(1)} #{x2.round(1)},#{y2.round(1)}"
        %(<path class="edge" data-from="#{e(a)}" data-to="#{e(b)}" d="#{d}"><title>#{e(label(a, manifest))} → #{e(b)} #{e(set)}</title></path>)
      end.join("\n")
      svg_nodes = names.map do |n|
        x, y = pos[n]
        i = info[n]
        badges = +""
        badges << %(<text class="badge up" x="#{NODE_W - 10}" y="16" text-anchor="end">↑ #{e(i[:newest])}</text>) if i[:newest]
        badges << %(<text class="badge warn" x="#{NODE_W - 10}" y="16" text-anchor="end">pre</text>) if i[:pre]
        %(<g class="node #{i[:status]}" data-id="#{e(n)}" transform="translate(#{x.round(1)},#{y.round(1)})" tabindex="0">
  <rect width="#{NODE_W}" height="#{NODE_H}" rx="9"/>
  <text class="nm" x="12" y="19">#{e(i[:title])}</text>
  <text class="vr" x="12" y="36">#{e(i[:sub])}</text>#{badges}
</g>)
      end.join("\n")
      rows = names.reject { |n| n == :root }.map do |n|
        i = info[n]
        why = case i[:status]
              when "latest" then "newest available"
              when "held" then "held back: #{i[:blockers].join('; ')}"
              else "newer #{i[:newest]} exists (not blocked by constraints)"
              end
        by = graph.dependents(n).map { |d, s| "#{e(d == :root ? manifest.name : d)} <code>#{e(s)}</code>" }.join(", ")
        %(<tr data-id="#{e(n)}" class="#{i[:status]}"><td class="pk">#{e(n)}</td><td class="mono">#{e(i[:sub])}</td><td><span class="pill #{i[:status]}">#{e(i[:status])}</span> #{e(why)}</td><td>#{by}</td></tr>)
      end.join("\n")

      <<~HTML
        <!doctype html>
        <html lang="en">
        <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Pinion — #{e(manifest.name)}</title>
        <style>
        :root{--bg:#f6f4ef;--panel:#ffffff;--ink:#1d1b16;--mute:#6f6a5d;--line:#d9d3c4;--accent:#b4491f;--ok:#2f7d4f;--warn:#b7791f;--held:#b4491f;--edge:#9a927f;--node:#fffdf8;--rootfill:#1d1b16;--rootink:#f6f4ef}
        @media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14130f;--panel:#1c1a15;--ink:#ece7da;--mute:#9a937f;--line:#33302a;--accent:#e8794a;--ok:#5fb383;--warn:#e0a84a;--held:#e8794a;--edge:#6b6556;--node:#221f19;--rootfill:#ece7da;--rootink:#14130f}}
        :root[data-theme=dark]{--bg:#14130f;--panel:#1c1a15;--ink:#ece7da;--mute:#9a937f;--line:#33302a;--accent:#e8794a;--ok:#5fb383;--warn:#e0a84a;--held:#e8794a;--edge:#6b6556;--node:#221f19;--rootfill:#ece7da;--rootink:#14130f}
        *{box-sizing:border-box}
        body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
        .mono,code,.vr,.badge{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
        header{padding:28px 16px 8px;max-width:1180px;margin:0 auto}
        h1{margin:0;font-size:26px;letter-spacing:-.01em}
        h1 span{color:var(--accent)}
        .sub{color:var(--mute);margin:4px 0 0}
        .stats{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 0}
        .stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 14px;min-width:110px}
        .stat b{display:block;font-size:22px;font-variant-numeric:tabular-nums}
        .stat i{font-style:normal;color:var(--mute);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
        main{max-width:1180px;margin:0 auto;padding:16px}
        .bar{display:flex;gap:10px;align-items:center;margin:8px 0 12px;flex-wrap:wrap}
        input[type=search]{flex:1;min-width:180px;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);font:inherit}
        button{padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--ink);font:inherit;cursor:pointer}
        button:hover{border-color:var(--accent)}
        .legend{display:flex;gap:14px;color:var(--mute);font-size:13px;flex-wrap:wrap}
        .legend em{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px;border:1.5px solid}
        .canvas{overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:14px}
        svg{display:block}
        .edge{fill:none;stroke:var(--edge);stroke-width:1.4;opacity:.75;transition:opacity .15s}
        .node rect{fill:var(--node);stroke:var(--line);stroke-width:1.5;transition:opacity .15s,stroke .15s}
        .node.latest rect{stroke:var(--ok)}
        .node.held rect{stroke:var(--held);stroke-width:2}
        .node.behind rect{stroke:var(--warn)}
        .node.root rect{fill:var(--rootfill);stroke:var(--rootfill)}
        .node.root text{fill:var(--rootink)}
        .node text{fill:var(--ink)}
        .nm{font-weight:650;font-size:14px}
        .vr{font-size:12px;fill:var(--mute)!important}
        .node.root .vr{fill:var(--rootink)!important;opacity:.7}
        .badge{font-size:11px}
        .badge.up{fill:var(--held)!important}.badge.warn{fill:var(--warn)!important}
        .node{cursor:pointer;outline:none}.node:focus-visible rect{stroke:var(--accent);stroke-width:3}
        .dim{opacity:.13}
        .hot.edge{stroke:var(--accent);stroke-width:2.4;opacity:1}
        table{width:100%;border-collapse:collapse;margin-top:22px;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden;font-size:14px}
        th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
        th{font-size:12px;color:var(--mute);text-transform:uppercase;letter-spacing:.06em;background:color-mix(in srgb,var(--panel) 90%,var(--ink) 4%)}
        tr:last-child td{border-bottom:0}
        td.pk{font-weight:650}
        tr.hl td{background:color-mix(in srgb,var(--accent) 12%,transparent)}
        .pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;border:1px solid;margin-right:4px}
        .pill.latest{color:var(--ok)}.pill.held{color:var(--held)}.pill.behind{color:var(--warn)}
        code{font-size:12.5px;background:color-mix(in srgb,var(--ink) 7%,transparent);padding:1px 5px;border-radius:5px}
        footer{max-width:1180px;margin:0 auto;padding:6px 16px 36px;color:var(--mute);font-size:13px}
        @media (max-width:640px){th:nth-child(4),td:nth-child(4){display:none}}
        </style>
        </head>
        <body>
        <header>
          <h1><span>◈</span> #{e(manifest.name)}</h1>
          <p class="sub">#{result.solution.length} packages resolved by Pinion · #{result.stats[:decisions]} decisions · #{result.stats[:conflicts]} conflicts resolved · click a package to trace what it needs and what needs it</p>
          <div class="stats">
            <div class="stat"><b>#{result.solution.length}</b><i>packages</i></div>
            <div class="stat"><b>#{manifest.dependencies.length}</b><i>direct</i></div>
            <div class="stat"><b>#{latest}</b><i>on newest</i></div>
            <div class="stat"><b>#{held}</b><i>held back</i></div>
          </div>
        </header>
        <main>
          <div class="bar">
            <input type="search" id="q" placeholder="Filter packages…" aria-label="Filter packages">
            <button id="reset" type="button">Reset</button>
            <button id="theme" type="button" aria-label="Toggle theme">Theme</button>
          </div>
          <div class="legend">
            <span><em style="border-color:var(--ok)"></em>on newest</span>
            <span><em style="border-color:var(--held)"></em>held back by a constraint</span>
            <span><em style="border-color:var(--warn)"></em>newer exists, unconstrained</span>
          </div>
          <div class="canvas" style="margin-top:10px"><svg id="g" width="#{width.round}" height="#{height.round}" viewBox="0 0 #{width.round} #{height.round}" role="img" aria-label="Dependency graph">
        #{svg_edges}
        #{svg_nodes}
          </svg></div>
          <table id="t"><thead><tr><th>Package</th><th>Version</th><th>Status</th><th>Required by</th></tr></thead><tbody>
        #{rows}
          </tbody></table>
        </main>
        <footer>Generated by Pinion. Edges are labelled on hover with the constraint that created them.</footer>
        <script>
        const DATA = #{JSON.generate(data).gsub('</', '<\/')};
        const out = {}, inn = {};
        for (const [a, b] of DATA.edges) { (out[a] ||= []).push(b); (inn[b] ||= []).push(a); }
        const nodes = [...document.querySelectorAll('.node')], edges = [...document.querySelectorAll('.edge')], rows = [...document.querySelectorAll('#t tbody tr')];
        function walk(start, adj) { const seen = new Set([start]), st = [start]; while (st.length) { for (const m of adj[st.pop()] || []) if (!seen.has(m)) { seen.add(m); st.push(m); } } return seen; }
        function focus(id) {
          const keep = new Set([...walk(id, out), ...walk(id, inn)]);
          nodes.forEach(n => n.classList.toggle('dim', !keep.has(n.dataset.id)));
          edges.forEach(e => { const on = keep.has(e.dataset.from) && keep.has(e.dataset.to); e.classList.toggle('dim', !on); e.classList.toggle('hot', on); });
          rows.forEach(r => r.classList.toggle('hl', r.dataset.id === id));
        }
        function reset() { document.querySelectorAll('.dim,.hot,.hl').forEach(x => x.classList.remove('dim', 'hot', 'hl')); }
        nodes.forEach(n => { n.addEventListener('click', e => { e.stopPropagation(); focus(n.dataset.id); }); n.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); focus(n.dataset.id); } }); });
        document.getElementById('g').addEventListener('click', reset);
        document.getElementById('reset').addEventListener('click', () => { document.getElementById('q').value = ''; reset(); rows.forEach(r => r.hidden = false); });
        document.addEventListener('keydown', e => { if (e.key === 'Escape') document.getElementById('reset').click(); });
        document.getElementById('q').addEventListener('input', e => {
          const q = e.target.value.trim().toLowerCase(); reset();
          rows.forEach(r => r.hidden = q && !r.dataset.id.toLowerCase().includes(q));
          if (q) { const hit = nodes.filter(n => n.dataset.id.toLowerCase().includes(q)); nodes.forEach(n => n.classList.toggle('dim', !hit.includes(n))); edges.forEach(x => x.classList.add('dim')); }
        });
        document.getElementById('theme').addEventListener('click', () => {
          const r = document.documentElement, dark = matchMedia('(prefers-color-scheme: dark)').matches;
          const cur = r.dataset.theme || (dark ? 'dark' : 'light'); r.dataset.theme = cur === 'dark' ? 'light' : 'dark';
        });
        </script>
        </body>
        </html>
      HTML
    end

    def label(n, manifest) = n == :root ? manifest.name : n
  end
end
