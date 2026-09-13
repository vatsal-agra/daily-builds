"""Exports REAL protocol transcripts (not scripted/fake data) as JSON for
the self-contained HTML visualizer in visualizer/index.html.

Every number in the exported payload comes from an actual run of this
toolkit's own library code with a fixed seed, so the visualizer is
literally showing "here is what really happened," reproducibly.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from veil.group import STANDARD_GROUP as G
from veil import schnorr as S
from veil import fiatshamir as FS
from veil import orproof as OR
from veil import coloring as C
from veil import simulator as SIM

_HERE = Path(__file__).resolve().parent.parent / "visualizer"


def _schnorr_payload(rng: random.Random) -> dict:
    kp = S.generate_keypair(G, rng)
    tr = S.run_interactive_proof(G, kp, rng)
    accepted = S.verify(G, kp.y, tr.t, tr.c, tr.s)

    wrong_x = (kp.x + 1) % G.q
    t2, r2 = S.commit(G, rng)
    c2 = S.challenge(G, rng)
    s2 = S.respond(G, wrong_x, r2, c2)
    cheat_accepted = S.verify(G, kp.y, t2, c2, s2)

    t3, r3 = S.commit(G, rng)
    c3a = S.challenge(G, rng)
    s3a = S.respond(G, kp.x, r3, c3a)
    c3b = S.challenge(G, rng)
    while c3b == c3a:
        c3b = S.challenge(G, rng)
    s3b = S.respond(G, kp.x, r3, c3b)
    extracted = S.extract_witness(G, kp.y, S.Transcript(t3, c3a, s3a), S.Transcript(t3, c3b, s3b))

    sim_tr = SIM.simulate_schnorr_transcript(G, kp.y, rng)

    return {
        "secret_x": str(kp.x),
        "public_y": str(kp.y),
        "honest": {"t": str(tr.t), "c": str(tr.c), "s": str(tr.s), "accepted": accepted},
        "cheat": {"t": str(t2), "c": str(c2), "s": str(s2), "accepted": cheat_accepted},
        "extraction": {
            "t": str(t3),
            "c1": str(c3a),
            "s1": str(s3a),
            "c2": str(c3b),
            "s2": str(s3b),
            "extracted_x": str(extracted),
            "matches": extracted == kp.x,
        },
        "simulated": {
            "t": str(sim_tr.t),
            "c": str(sim_tr.c),
            "s": str(sim_tr.s),
            "note": "produced with NO knowledge of x, by picking c and s first",
        },
    }


def _coloring_payload(rng: random.Random, rounds: int = 8) -> dict:
    round_data = []
    for _ in range(rounds):
        t = C.run_round(C.HOUSE_GRAPH, C.HOUSE_COLORING, rng)
        u, v = C.HOUSE_GRAPH.edges[t.edge_index]
        round_data.append(
            {
                "commitments": [c.hex()[:16] + "…" for c in t.commitments],
                "challenged_edge": [u, v],
                "revealed_color_u": t.opening.color_u,
                "revealed_color_v": t.opening.color_v,
                "accepted": t.accepted,
            }
        )
    bound = C.soundness_error_bound(len(C.HOUSE_GRAPH.edges), rounds)
    return {
        "num_vertices": C.HOUSE_GRAPH.num_vertices,
        "edges": [list(e) for e in C.HOUSE_GRAPH.edges],
        "num_edges": len(C.HOUSE_GRAPH.edges),
        "rounds": round_data,
        "soundness_bound": bound,
    }


def _orproof_payload(rng: random.Random, n: int = 5) -> dict:
    members = [S.generate_keypair(G, rng) for _ in range(n)]
    pubkeys = [m.y for m in members]
    secret_index = n // 2
    message = b"anon vote: yes"
    proof = OR.prove_or(G, secret_index, members[secret_index].x, pubkeys, message, rng)
    verified = OR.verify_or(G, pubkeys, message, proof)
    return {
        "n_members": n,
        "public_keys": [str(y) for y in pubkeys],
        "message": message.decode(),
        "t_list": [str(t) for t in proof.t_list],
        "c_list": [str(c) for c in proof.c_list],
        "s_list": [str(s) for s in proof.s_list],
        "verified": verified,
        "note": "the real signer's index is NOT in this payload on purpose — that's the point",
    }


def generate_payload(seed: int = 20260913) -> dict:
    rng = random.Random(seed)
    return {
        "seed": seed,
        "group": {"p": str(G.p), "q": str(G.q), "g": str(G.g), "bits": G.p.bit_length()},
        "schnorr": _schnorr_payload(rng),
        "coloring": _coloring_payload(rng),
        "orproof": _orproof_payload(rng),
    }


def build_visualizer(seed: int = 20260913) -> Path:
    """Read visualizer/template.html, inject a real generated payload as
    inline JSON, and write visualizer/index.html."""
    template_path = _HERE / "template.html"
    output_path = _HERE / "index.html"
    template = template_path.read_text()
    payload = generate_payload(seed)
    injected = template.replace(
        "/*__VEIL_DATA__*/", json.dumps(payload, indent=2)
    )
    output_path.write_text(injected)
    return output_path


if __name__ == "__main__":
    path = build_visualizer()
    print(f"Wrote {path}")
