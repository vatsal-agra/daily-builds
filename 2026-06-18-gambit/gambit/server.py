"""A stdlib HTTP server that serves a browser board you play against the *real*
Python engine. No engine logic is duplicated in JavaScript: the page sends the
current FEN and chosen move to the server, which validates with the real move
generator and replies with the engine's move and analysis.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .board import Board, move_uci, sq_name
from .movegen import legal_moves
from .san import to_san, from_san
from .engine import Engine, format_score, result_text


def _legal_payload(board: Board) -> dict:
    """Map of from-square -> list of legal destinations (with promo flags)."""
    moves = {}
    for mv in legal_moves(board):
        frm = sq_name(mv & 0xFF)
        to = sq_name((mv >> 8) & 0xFF)
        moves.setdefault(frm, []).append({
            "to": to, "uci": move_uci(mv), "san": to_san(board, mv),
        })
    over = result_text(board)
    return {
        "fen": board.to_fen(),
        "turn": "w" if board.side == 0 else "b",
        "moves": moves,
        "result": over,
    }


class Handler(BaseHTTPRequestHandler):
    engine: Engine = None  # set by serve()

    def log_message(self, *a):
        pass  # quiet

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/api/new":
            self._send(200, json.dumps(_legal_payload(Board.startpos())))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, json.dumps({"error": "bad json"}))
            return

        if self.path == "/api/state":
            try:
                board = Board.from_fen(req["fen"])
            except (ValueError, KeyError) as e:
                self._send(400, json.dumps({"error": str(e)}))
                return
            self._send(200, json.dumps(_legal_payload(board)))
            return

        if self.path == "/api/move":
            try:
                board = Board.from_fen(req["fen"])
            except (ValueError, KeyError) as e:
                self._send(400, json.dumps({"error": str(e)}))
                return
            # apply the human move (uci, e.g. e2e4 or e7e8q)
            human_uci = req.get("uci")
            applied = None
            if human_uci:
                for mv in legal_moves(board):
                    if move_uci(mv).replace(" ", "") == human_uci:
                        applied = mv
                        break
                if applied is None:
                    self._send(400, json.dumps({"error": f"illegal move {human_uci}"}))
                    return
                san = to_san(board, applied)
                board.make_move(applied)
            else:
                san = None

            over = result_text(board)
            resp = {"human_san": san, "after_human": _legal_payload(board)}
            if over is None:
                res = self.engine.best_move(board)
                emv = res.best_move
                resp["engine"] = {
                    "uci": move_uci(emv).replace(" ", ""),
                    "san": to_san(board, emv),
                    "score": format_score(res.score),
                    "depth": res.depth,
                    "nodes": res.nodes,
                    "from": sq_name(emv & 0xFF),
                    "to": sq_name((emv >> 8) & 0xFF),
                }
                board.make_move(emv)
                resp["state"] = _legal_payload(board)
            else:
                resp["engine"] = None
                resp["state"] = _legal_payload(board)
            self._send(200, json.dumps(resp))
            return

        self._send(404, json.dumps({"error": "not found"}))


def serve(host="127.0.0.1", port=8000, depth=4, movetime=2.0):
    Handler.engine = Engine(depth=depth, movetime=movetime)
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Gambit board serving at http://{host}:{port}/  "
          f"(engine: depth {depth}, {movetime}s/move)")
    print("Press Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping.")
        httpd.shutdown()


PAGE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gambit — play the engine</title>
<style>
  :root{--bg:#11151c;--ink:#e8edf6;--muted:#8b97ad;--light:#e9e0cf;--dark:#7d9061;
    --accent:#f2c14e;--hi:#f6e58d;--mv:#bcd07a;--line:#2a3344;--panel:#1b2230;}
  *{box-sizing:border-box}
  body{margin:0;background:radial-gradient(1200px 700px at 70% -10%,#1d2740,#0c0f15);
    color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
  .wrap{max-width:880px;margin:0 auto;padding:26px 18px}
  h1{margin:0 0 2px}.q{color:var(--accent)}
  .sub{color:var(--muted);margin:0 0 18px}
  .row{display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start}
  .board{width:480px;height:480px;display:grid;grid-template-columns:repeat(8,1fr);
    grid-template-rows:repeat(8,1fr);border-radius:10px;overflow:hidden;
    box-shadow:0 14px 40px rgba(0,0,0,.5)}
  .sq{position:relative;display:flex;align-items:center;justify-content:center;
    font-size:42px;cursor:pointer;user-select:none}
  .sq.l{background:var(--light)}.sq.d{background:var(--dark)}
  .sq.wpiece{color:#f7fbff;text-shadow:0 0 2px #000,0 1px 2px #0008}
  .sq.bpiece{color:#141a22}
  .sq.sel::after{content:"";position:absolute;inset:0;background:var(--accent);opacity:.5;mix-blend-mode:multiply}
  .sq.last::after{content:"";position:absolute;inset:0;background:var(--hi);opacity:.4;mix-blend-mode:multiply}
  .sq .dot{position:absolute;width:30%;height:30%;border-radius:50%;background:#0003}
  .sq.cap .dot{width:84%;height:84%;background:none;border:5px solid #0003;border-radius:50%}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px;min-width:250px;flex:1}
  button{background:#243049;color:var(--ink);border:1px solid var(--line);border-radius:9px;
    padding:9px 13px;font-size:14px;cursor:pointer}
  button:hover{background:#2e3c5a}
  .status{font-size:17px;font-weight:700;margin:4px 0 10px}
  .info{color:var(--muted);font-size:14px;white-space:pre-wrap}
  .log{margin-top:12px;max-height:230px;overflow:auto;font-variant-numeric:tabular-nums;font-size:14px}
  .log b{color:var(--accent)}
  label{font-size:13px;color:var(--muted)}
  select{background:#243049;color:var(--ink);border:1px solid var(--line);border-radius:7px;padding:5px}
</style></head>
<body><div class="wrap">
  <h1>Gambit <span class="q">&#9819;</span> &mdash; play the engine</h1>
  <p class="sub">You are White. Click a piece, then its destination. The
     <b>real Python engine</b> replies (no JS engine — the server does the thinking).</p>
  <div class="row">
    <div><div class="board" id="board"></div></div>
    <div class="panel">
      <div class="status" id="status">Your move.</div>
      <div style="display:flex;gap:8px;align-items:center;margin-bottom:10px">
        <button onclick="newGame()">New game</button>
        <label>promote to
          <select id="promo"><option value="q">Queen</option><option value="r">Rook</option>
          <option value="b">Bishop</option><option value="n">Knight</option></select></label>
      </div>
      <div class="info" id="info"></div>
      <div class="log" id="log"></div>
    </div>
  </div>
</div>
<script>
const GLYPH={p:'♟',n:'♞',b:'♝',r:'♜',q:'♛',k:'♚'};
let state=null, sel=null, last=null, busy=false, moveNo=1;

async function api(path, body){
  const opt = body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{};
  const r = await fetch(path,opt); return r.json();
}
function parseFEN(fen){
  const rows=fen.split(' ')[0].split('/'); const g=[];
  for(let i=0;i<8;i++){const rank=7-i;g[rank]=[];let f=0;
    for(const ch of rows[i]){ if(/\d/.test(ch)){for(let k=0;k<+ch;k++)g[rank][f++]=null;} else g[rank][f++]=ch; }}
  return g;
}
function draw(){
  const g=parseFEN(state.fen); const b=document.getElementById('board'); b.innerHTML='';
  const dests = sel && state.moves[sel] ? state.moves[sel].map(m=>m.to) : [];
  for(let i=0;i<8;i++){const rank=7-i;
    for(let f=0;f<8;f++){
      const sq=document.createElement('div'); const light=(rank+f)%2===1;
      sq.className='sq '+(light?'l':'d'); const name='abcdefgh'[f]+(rank+1);
      const pc=g[rank][f];
      if(pc){sq.classList.add(pc===pc.toUpperCase()?'wpiece':'bpiece'); sq.textContent=GLYPH[pc.toLowerCase()];}
      if(name===sel) sq.classList.add('sel');
      if(last && (name===last[0]||name===last[1])) sq.classList.add('last');
      if(dests.includes(name)){ if(pc) sq.classList.add('cap'); const d=document.createElement('span'); d.className='dot'; sq.appendChild(d); }
      sq.onclick=()=>click(name);
      b.appendChild(sq);
    }}
}
function click(name){
  if(busy || state.turn!=='w' || state.result) return;
  if(sel && state.moves[sel]){
    const m=state.moves[sel].find(x=>x.to===name);
    if(m){ doMove(m); return; }
  }
  sel = state.moves[name] ? name : null; draw();
}
async function doMove(m){
  let uci=m.uci.replace(' ','');
  // promotion: uci already ends with a letter if from the move list; pick chosen piece
  if(uci.length===5){ uci=uci.slice(0,4)+document.getElementById('promo').value; }
  busy=true; sel=null; document.getElementById('status').textContent='thinking…';
  const r=await api('/api/move',{fen:state.fen,uci:uci});
  if(r.error){ document.getElementById('status').textContent='error: '+r.error; busy=false; return; }
  logMove('w', r.human_san);
  last=[uci.slice(0,2),uci.slice(2,4)];
  if(r.engine){
    state=r.state; last=[r.engine.from,r.engine.to];
    logMove('b', r.engine.san);
    document.getElementById('info').textContent =
      `engine: ${r.engine.san}\nscore ${r.engine.score} · depth ${r.engine.depth} · ${r.engine.nodes.toLocaleString()} nodes`;
  } else { state=r.state; }
  busy=false; updateStatus(); draw();
}
function logMove(col,san){
  const l=document.getElementById('log');
  if(col==='w'){ l.innerHTML+=`<div><b>${moveNo}.</b> ${san} `; }
  else { l.lastChild.innerHTML+=san; moveNo++; }
  l.scrollTop=l.scrollHeight;
}
function updateStatus(){
  const s=document.getElementById('status');
  if(state.result){ s.textContent = state.result==='1/2-1/2'?'Draw.':(state.result==='1-0'?'White wins! 🏆':'Black (engine) wins.'); }
  else s.textContent = state.turn==='w'?'Your move.':'engine to move…';
}
async function newGame(){
  state=await api('/api/new'); sel=null; last=null; moveNo=1; busy=false;
  document.getElementById('log').innerHTML=''; document.getElementById('info').textContent='';
  updateStatus(); draw();
}
newGame();
</script>
</body></html>"""
