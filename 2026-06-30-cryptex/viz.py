"""Generate a self-contained HTML visualizer for Cryptex.

Shows:
  - AES S-box: the 16×16 GF(2^8) derived table, colored by value
  - AES key schedule: expansion of the first 256-bit key round by round
  - SHA-256 compression: all 64 rounds of the first compression step
  - Interactive encrypt/decrypt demo: AES-256-CTR in JavaScript
"""

import json


def generate_viz(output_path: str) -> None:
    from gf256 import SBOX, INV_SBOX, RCON, mul
    from sha256 import K, H0, _compress
    from aes import key_schedule, _get_round_key

    # Precompute AES S-box data
    sbox_data = SBOX[:]
    inv_sbox_data = INV_SBOX[:]

    # Precompute AES-256 key schedule for a sample key
    sample_key = bytes.fromhex(
        "000102030405060708090a0b0c0d0e0f"
        "101112131415161718191a1b1c1d1e1f"
    )
    W = key_schedule(sample_key)
    round_keys = []
    for rnd in range(15):
        rk = _get_round_key(W, rnd)
        flat = [rk[r][c] for c in range(4) for r in range(4)]
        round_keys.append(flat)

    # SHA-256 trace for "abc"
    import struct
    msg = b"abc"
    bit_len = len(msg) * 8
    padded = bytearray(msg)
    padded.append(0x80)
    while len(padded) % 64 != 56:
        padded.append(0x00)
    padded += struct.pack(">Q", bit_len)
    block0 = bytes(padded[:64])

    H = list(H0)
    w_schedule = list(struct.unpack(">16I", block0))
    for i in range(16, 64):
        def ror(x, n): return ((x >> n) | (x << (32 - n))) & 0xFFFFFFFF
        s0 = ror(w_schedule[i-15], 7) ^ ror(w_schedule[i-15], 18) ^ (w_schedule[i-15] >> 3)
        s1 = ror(w_schedule[i-2], 17) ^ ror(w_schedule[i-2], 19) ^ (w_schedule[i-2] >> 10)
        w_schedule.append((w_schedule[i-16] + s0 + w_schedule[i-7] + s1) & 0xFFFFFFFF)

    sha_rounds = []
    a, b, c, d, e, f, g, h = H
    for i in range(64):
        def ror(x, n): return ((x >> n) | (x << (32 - n))) & 0xFFFFFFFF
        def u32(x): return x & 0xFFFFFFFF
        S1 = ror(e, 6) ^ ror(e, 11) ^ ror(e, 25)
        ch = (e & f) ^ (~e & g) & 0xFFFFFFFF
        temp1 = (h + S1 + ch + K[i] + w_schedule[i]) & 0xFFFFFFFF
        S0 = ror(a, 2) ^ ror(a, 13) ^ ror(a, 22)
        maj = (a & b) ^ (a & c) ^ (b & c)
        temp2 = (S0 + maj) & 0xFFFFFFFF
        sha_rounds.append({
            "i": i,
            "a": f"{a:08x}", "b": f"{b:08x}", "c": f"{c:08x}", "d": f"{d:08x}",
            "e": f"{e:08x}", "f": f"{f:08x}", "g": f"{g:08x}", "h": f"{h:08x}",
            "W": f"{w_schedule[i]:08x}", "K": f"{K[i]:08x}",
            "T1": f"{temp1:08x}", "T2": f"{temp2:08x}",
        })
        h, g, f, e, d, c, b, a = g, f, e, (d + temp1) & 0xFFFFFFFF, c, b, a, (temp1 + temp2) & 0xFFFFFFFF

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cryptex — Cryptography Visualizer</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0a0e1a; color: #e2e8f0; font-family: 'Courier New', monospace; font-size: 13px; }}
  h1 {{ text-align: center; padding: 24px; color: #7dd3fc; font-size: 22px; letter-spacing: 4px; }}
  h2 {{ color: #38bdf8; font-size: 14px; letter-spacing: 2px; margin-bottom: 12px; }}
  .nav {{ display: flex; justify-content: center; gap: 8px; padding: 0 20px 20px; flex-wrap: wrap; }}
  .nav button {{ background: #1e293b; border: 1px solid #334155; color: #94a3b8; padding: 8px 16px;
                 border-radius: 4px; cursor: pointer; font-family: inherit; font-size: 12px; }}
  .nav button.active {{ background: #0369a1; border-color: #0284c7; color: #fff; }}
  .panel {{ display: none; max-width: 1100px; margin: 0 auto; padding: 0 20px 40px; }}
  .panel.visible {{ display: block; }}
  .sbox-grid {{ display: inline-grid; grid-template-columns: repeat(16, 28px); gap: 1px; border: 1px solid #334155; }}
  .sbox-cell {{ width: 28px; height: 28px; display: flex; align-items: center; justify-content: center;
                font-size: 10px; color: #fff; cursor: pointer; transition: transform 0.1s; }}
  .sbox-cell:hover {{ transform: scale(1.4); z-index: 10; position: relative; }}
  .rk-row {{ display: flex; gap: 4px; margin-bottom: 4px; align-items: center; }}
  .rk-label {{ width: 70px; color: #64748b; font-size: 11px; }}
  .rk-byte {{ width: 22px; height: 22px; display: flex; align-items: center; justify-content: center;
              font-size: 9px; border-radius: 2px; }}
  .sha-table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  .sha-table th {{ background: #1e293b; padding: 4px 6px; color: #38bdf8; text-align: left; position: sticky; top: 0; }}
  .sha-table td {{ padding: 3px 6px; border-bottom: 1px solid #1e293b; font-family: monospace; }}
  .sha-table tr:nth-child(even) {{ background: #0f172a; }}
  .sha-scroll {{ max-height: 420px; overflow-y: auto; border: 1px solid #1e293b; border-radius: 4px; }}
  .demo-box {{ background: #1e293b; border-radius: 8px; padding: 20px; margin-bottom: 16px; }}
  .demo-box label {{ color: #94a3b8; display: block; margin-bottom: 4px; font-size: 11px; }}
  .demo-box input, .demo-box textarea {{
    width: 100%; background: #0f172a; border: 1px solid #334155; color: #e2e8f0;
    padding: 8px; border-radius: 4px; font-family: monospace; font-size: 12px;
    margin-bottom: 10px;
  }}
  .demo-box textarea {{ height: 80px; resize: vertical; }}
  .btn {{ background: #0369a1; color: #fff; border: none; padding: 8px 20px; border-radius: 4px;
          cursor: pointer; font-family: inherit; font-size: 12px; margin-right: 8px; }}
  .btn:hover {{ background: #0284c7; }}
  .btn-danger {{ background: #dc2626; }}
  .btn-danger:hover {{ background: #b91c1c; }}
  .output {{ background: #0f172a; border: 1px solid #334155; border-radius: 4px; padding: 10px;
             font-family: monospace; font-size: 11px; color: #22d3ee; word-break: break-all; min-height: 40px; }}
  .info-badge {{ display: inline-block; background: #164e63; color: #67e8f9; border-radius: 3px;
                 padding: 1px 6px; font-size: 10px; margin-left: 6px; }}
  .legend {{ display: flex; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; font-size: 11px; }}
  .legend-item {{ display: flex; align-items: center; gap: 4px; }}
  .legend-dot {{ width: 12px; height: 12px; border-radius: 2px; }}
  .desc {{ color: #64748b; font-size: 11px; line-height: 1.6; margin-bottom: 14px; }}
</style>
</head>
<body>
<h1>⚿ CRYPTEX VISUALIZER</h1>
<div class="nav">
  <button class="active" onclick="show('sbox')">AES S-box</button>
  <button onclick="show('keysched')">Key Schedule</button>
  <button onclick="show('sha256')">SHA-256 Rounds</button>
  <button onclick="show('demo')">Live Demo</button>
</div>

<!-- AES S-BOX -->
<div id="panel-sbox" class="panel visible">
  <h2>AES S-BOX — GF(2⁸) Multiplicative Inverse + Affine Transform</h2>
  <p class="desc">
    Each cell shows <code>SBOX[row*16 + col]</code>. The S-box is NOT a lookup table from a textbook —
    it is computed live: <b>S(a) = affine_transform(GF(2⁸)_inverse(a))</b>.
    GF(2⁸) uses the AES irreducible polynomial x⁸+x⁴+x³+x+1 (0x11B).
    Color = value (dark=low, bright=high). Hover to see details.
  </p>
  <div class="legend">
    <div class="legend-item"><div class="legend-dot" style="background:#0f172a"></div>0x00</div>
    <div class="legend-item"><div class="legend-dot" style="background:#1e3a5f"></div>0x40</div>
    <div class="legend-item"><div class="legend-dot" style="background:#0369a1"></div>0x80</div>
    <div class="legend-item"><div class="legend-dot" style="background:#38bdf8"></div>0xC0</div>
    <div class="legend-item"><div class="legend-dot" style="background:#fff"></div>0xFF</div>
  </div>
  <div id="sbox-grid" class="sbox-grid"></div>
  <div id="sbox-info" style="margin-top:12px;color:#94a3b8;font-size:11px;height:40px"></div>

  <div style="margin-top:24px">
    <h2>INVERSE S-BOX</h2>
    <p class="desc">Used during AES decryption. INV_SBOX[SBOX[x]] = x for all x.</p>
    <div id="inv-sbox-grid" class="sbox-grid"></div>
  </div>
</div>

<!-- KEY SCHEDULE -->
<div id="panel-keysched" class="panel">
  <h2>AES-256 KEY SCHEDULE — 14 Round Keys from 32-byte Input Key</h2>
  <p class="desc">
    Key: <code>000102...1e1f</code> (FIPS 197 Appendix C.3). Each row is one 16-byte round key.
    Round 0 = first 16 bytes of the original key. Each subsequent key is derived using
    SubWord, RotWord, and XOR with Rcon. Color = byte value.
  </p>
  <div id="keysched-grid"></div>
</div>

<!-- SHA-256 ROUNDS -->
<div id="panel-sha256" class="panel">
  <h2>SHA-256 — 64 Compression Rounds on "abc"</h2>
  <p class="desc">
    SHA-256("abc") = <code>ba7816bf...</code>. Showing all 64 rounds of the single
    64-byte block. a–h are the 8 working variables (32-bit big-endian hex). W[i] is the
    message schedule word. T1 and T2 are the two temporary values updated each round.
  </p>
  <div class="sha-scroll">
    <table class="sha-table" id="sha-table">
      <thead><tr><th>#</th><th>a</th><th>b</th><th>c</th><th>d</th><th>e</th><th>f</th><th>g</th><th>h</th><th>W[i]</th><th>T1</th><th>T2</th></tr></thead>
      <tbody id="sha-tbody"></tbody>
    </table>
  </div>
</div>

<!-- LIVE DEMO -->
<div id="panel-demo" class="panel">
  <h2>LIVE DEMO — AES-256-CTR in Your Browser</h2>
  <p class="desc">
    AES-256 implemented in JavaScript (faithful port of the Python engine). The key schedule
    and 14-round cipher run live in your browser — no server, no WebCrypto API. Each encrypt
    generates a random 8-byte nonce. Ciphertext is base64(nonce + encrypted_bytes).
  </p>
  <div class="demo-box">
    <label>Key (64 hex chars = 32 bytes)</label>
    <input id="demo-key" type="text" placeholder="Generate one or paste yours" />
    <div style="margin-bottom:10px">
      <button class="btn" onclick="genKey()">Generate Random Key</button>
    </div>
    <label>Plaintext</label>
    <textarea id="demo-pt" placeholder="Enter text to encrypt...">Hello from AES-256-CTR implemented from scratch!</textarea>
    <button class="btn" onclick="demoEncrypt()">Encrypt</button>
    <button class="btn btn-danger" onclick="demoDecrypt()">Decrypt Ciphertext Below</button>
  </div>
  <div class="demo-box">
    <label>Ciphertext (base64: nonce || encrypted)</label>
    <div id="demo-ct" class="output">—</div>
  </div>
  <div class="demo-box">
    <label>Decrypted Text</label>
    <div id="demo-dec" class="output">—</div>
  </div>
</div>

<script>
// ─── Navigation ───────────────────────────────────────────────────────────
function show(id) {{
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('visible'));
  document.querySelectorAll('.nav button').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-' + id).classList.add('visible');
  document.querySelectorAll('.nav button').forEach(b => {{
    if (b.textContent.toLowerCase().includes(id.replace('sched','').replace('256','').trim())) b.classList.add('active');
  }});
}

// ─── S-box rendering ──────────────────────────────────────────────────────
const SBOX = {json.dumps(sbox_data)};
const INV_SBOX = {json.dumps(inv_sbox_data)};

function valueToColor(v) {{
  const r = Math.round(3 + (v/255) * 56);   // 3→59  (blue range)
  const g = Math.round((v/255) * 189);        // 0→189
  const b = Math.round(40 + (v/255) * 215);  // 40→255
  return `rgb(${{r*3}},${{g}},${{b}})`;
}}

function buildSboxGrid(container, data, prefix) {{
  let html = '';
  for (let i = 0; i < 256; i++) {{
    const v = data[i];
    const bg = valueToColor(v);
    html += `<div class="sbox-cell" style="background:${{bg}}" ` +
            `onmouseenter="showSboxInfo(${{i}},${{v}},'${{prefix}}')" ` +
            `data-val="${{v.toString(16).padStart(2,'0').toUpperCase()}}">` +
            `${{v.toString(16).padStart(2,'0').toUpperCase()}}</div>`;
  }}
  document.getElementById(container).innerHTML = html;
}}

function showSboxInfo(i, v, prefix) {{
  const inv = prefix === 'sbox' ? INV_SBOX[v] : SBOX[v];
  document.getElementById('sbox-info').innerHTML =
    `Input: 0x${{i.toString(16).padStart(2,'0').toUpperCase()}} ` +
    `→ ${{prefix.toUpperCase()}}[${{i}}] = 0x${{v.toString(16).padStart(2,'0').toUpperCase()}} ` +
    `→ Round-trip: 0x${{inv.toString(16).padStart(2,'0').toUpperCase()}} ` +
    `<span class="info-badge">${{prefix === 'sbox' ? 'INV_SBOX[SBOX[x]] = x' : 'SBOX[INV_SBOX[x]] = x'}}</span>`;
}}

buildSboxGrid('sbox-grid', SBOX, 'sbox');
buildSboxGrid('inv-sbox-grid', INV_SBOX, 'invsbox');

// ─── Key schedule rendering ────────────────────────────────────────────────
const ROUND_KEYS = {json.dumps(round_keys)};

function buildKeySchedule() {{
  let html = '';
  for (let rnd = 0; rnd < ROUND_KEYS.length; rnd++) {{
    html += `<div class="rk-row"><div class="rk-label">Round ${{rnd.toString().padStart(2,'0')}}</div>`;
    for (let i = 0; i < 16; i++) {{
      const v = ROUND_KEYS[rnd][i];
      const bg = valueToColor(v);
      const hex = v.toString(16).padStart(2,'0').toUpperCase();
      html += `<div class="rk-byte" style="background:${{bg}}" title="byte ${{i}}: 0x${{hex}}">${{hex}}</div>`;
    }}
    if (rnd < ROUND_KEYS.length - 1) {{
      html += `<div style="color:#334155;margin-left:4px;font-size:10px">↓ expand</div>`;
    }}
    html += '</div>';
  }}
  document.getElementById('keysched-grid').innerHTML = html;
}}
buildKeySchedule();

// ─── SHA-256 rounds ────────────────────────────────────────────────────────
const SHA_ROUNDS = {json.dumps(sha_rounds)};

function buildShaTable() {{
  let html = '';
  for (const r of SHA_ROUNDS) {{
    const colors = ['#ef4444','#f97316','#eab308','#22c55e','#06b6d4','#3b82f6','#8b5cf6','#ec4899'];
    const vals = ['a','b','c','d','e','f','g','h'].map((k,i) =>
      `<td style="color:${{colors[i]}}"><code>${{r[k]}}</code></td>`).join('');
    html += `<tr><td style="color:#64748b">${{r.i}}</td>${{vals}}` +
            `<td style="color:#94a3b8"><code>${{r.W}}</code></td>` +
            `<td style="color:#fbbf24"><code>${{r.T1}}</code></td>` +
            `<td style="color:#a78bfa"><code>${{r.T2}}</code></td></tr>`;
  }}
  document.getElementById('sha-tbody').innerHTML = html;
}}
buildShaTable();

// ─── AES-256-CTR JavaScript Implementation ────────────────────────────────
// GF(2^8) multiplication
function gfMul(a, b) {{
  let r = 0, x = a;
  for (let i = 0; i < 8; i++) {{
    if (b & 1) r ^= x;
    const hb = x & 0x80;
    x = (x << 1) & 0xFF;
    if (hb) x ^= 0x1B; // x^4+x^3+x+1 (low 8 bits of 0x11B)
    b >>= 1;
  }}
  return r;
}}

// Build S-box in JS (same algorithm as Python)
function buildSBOX_js() {{
  const s = new Uint8Array(256);
  function gfInv(a) {{
    if (a === 0) return 0;
    let r = 1, base = a, exp = 254;
    while (exp > 0) {{ if (exp & 1) r = gfMul(r, base); base = gfMul(base, base); exp >>= 1; }}
    return r;
  }}
  function rol8(v, n) {{ return ((v << n) | (v >> (8 - n))) & 0xFF; }}
  for (let i = 0; i < 256; i++) {{
    const b = gfInv(i);
    s[i] = b ^ rol8(b,1) ^ rol8(b,2) ^ rol8(b,3) ^ rol8(b,4) ^ 0x63;
  }}
  return s;
}}

const SBOX_JS = buildSBOX_js();
const RCON_JS = (() => {{ const r = new Uint8Array(11); let v = 1; for(let i=0;i<11;i++) {{ r[i]=v; v=gfMul(v,2); }} return r; }})();

function keyScheduleJS(key32) {{
  const W = [];
  for (let i = 0; i < 8; i++) W.push([key32[4*i],key32[4*i+1],key32[4*i+2],key32[4*i+3]]);
  for (let i = 8; i < 60; i++) {{
    let temp = [...W[i-1]];
    if (i % 8 === 0) {{
      temp = [temp[1],temp[2],temp[3],temp[0]].map(b => SBOX_JS[b]);
      temp[0] ^= RCON_JS[i/8 - 1];
    }} else if (i % 8 === 4) temp = temp.map(b => SBOX_JS[b]);
    W.push(W[i-8].map((b,j) => b ^ temp[j]));
  }}
  return W;
}}

function aesEncryptBlock(block, W) {{
  const state = Array.from({{length:4}}, (_,r) => Array.from({{length:4}}, (_,c) => block[r+4*c]));
  const addRK = (rnd) => {{ for(let r=0;r<4;r++) for(let c=0;c<4;c++) state[r][c]^=W[rnd*4+c][r]; }};
  const subBytes = () => {{ for(let r=0;r<4;r++) for(let c=0;c<4;c++) state[r][c]=SBOX_JS[state[r][c]]; }};
  const shiftRows = () => {{ for(let r=1;r<4;r++) {{ const t=state[r].splice(0,r); state[r].push(...t); }} }};
  const mixCols = () => {{
    for(let c=0;c<4;c++) {{
      const [s0,s1,s2,s3] = [state[0][c],state[1][c],state[2][c],state[3][c]];
      state[0][c]=gfMul(2,s0)^gfMul(3,s1)^s2^s3;
      state[1][c]=s0^gfMul(2,s1)^gfMul(3,s2)^s3;
      state[2][c]=s0^s1^gfMul(2,s2)^gfMul(3,s3);
      state[3][c]=gfMul(3,s0)^s1^s2^gfMul(2,s3);
    }}
  }};
  addRK(0);
  for(let rnd=1;rnd<14;rnd++) {{ subBytes(); shiftRows(); mixCols(); addRK(rnd); }}
  subBytes(); shiftRows(); addRK(14);
  return Array.from({{length:16}}, (_,i) => state[i%4][Math.floor(i/4)]);
}}

function aes256CTR(key32, nonce8, data) {{
  const W = keyScheduleJS(key32);
  const out = new Uint8Array(data.length);
  for(let i=0;i<data.length;i+=16) {{
    const ctr = Math.floor(i/16);
    const cb = [...nonce8, ...[(ctr>>56)&0xFF,(ctr>>48)&0xFF,(ctr>>40)&0xFF,(ctr>>32)&0xFF,
                               (ctr>>24)&0xFF,(ctr>>16)&0xFF,(ctr>>8)&0xFF, ctr&0xFF]];
    const ks = aesEncryptBlock(cb, W);
    for(let j=0;j<16&&i+j<data.length;j++) out[i+j] = data[i+j] ^ ks[j];
  }}
  return out;
}}

function hexToBytes(h) {{ return new Uint8Array(h.match(/../g).map(b=>parseInt(b,16))); }}
function bytesToB64(b) {{ return btoa(String.fromCharCode(...b)); }}
function b64ToBytes(s) {{ return new Uint8Array(atob(s).split('').map(c=>c.charCodeAt(0))); }}

function genKey() {{
  const key = new Uint8Array(32);
  crypto.getRandomValues(key);
  document.getElementById('demo-key').value = Array.from(key).map(b=>b.toString(16).padStart(2,'0')).join('');
}}

function demoEncrypt() {{
  const keyHex = document.getElementById('demo-key').value.trim();
  if (keyHex.length !== 64) {{ alert('Key must be 64 hex chars'); return; }}
  const key = hexToBytes(keyHex);
  const nonce = new Uint8Array(8);
  crypto.getRandomValues(nonce);
  const pt = new TextEncoder().encode(document.getElementById('demo-pt').value);
  const ct = aes256CTR(key, nonce, pt);
  const payload = new Uint8Array(8 + ct.length);
  payload.set(nonce); payload.set(ct, 8);
  document.getElementById('demo-ct').textContent = bytesToB64(payload);
  document.getElementById('demo-dec').textContent = '—';
}}

function demoDecrypt() {{
  const keyHex = document.getElementById('demo-key').value.trim();
  if (keyHex.length !== 64) {{ alert('Key must be 64 hex chars'); return; }}
  const key = hexToBytes(keyHex);
  const b64 = document.getElementById('demo-ct').textContent.trim();
  if (b64 === '—') {{ alert('Encrypt something first'); return; }}
  const payload = b64ToBytes(b64);
  const nonce = payload.slice(0, 8);
  const ct = payload.slice(8);
  const pt = aes256CTR(key, nonce, ct);
  try {{
    document.getElementById('demo-dec').textContent = new TextDecoder().decode(pt);
  }} catch(e) {{
    document.getElementById('demo-dec').textContent = Array.from(pt).map(b=>b.toString(16).padStart(2,'0')).join(' ');
  }}
}}

// Auto-generate a key
genKey();
</script>
</body>
</html>"""

    with open(output_path, "w") as f:
        f.write(html)
