"""Veil command-line tool: `python3 -m veil.cli <subcommand> ...`

Every subcommand runs a REAL protocol execution against the toolkit's
library code (no canned output) and prints what actually happened.
"""

from __future__ import annotations

import argparse
import random
import sys

from veil.group import STANDARD_GROUP, generate_safe_prime_group, is_safe_prime_group
from veil import schnorr as S
from veil import fiatshamir as FS
from veil import orproof as OR
from veil import coloring as C


def _rng(seed: int | None) -> random.Random:
    return random.Random(seed) if seed is not None else random.Random()


def cmd_group_info(args: argparse.Namespace) -> int:
    g = STANDARD_GROUP
    print("Schnorr group (safe prime p = 2q + 1):")
    print(f"  p = {g.p}")
    print(f"    ({g.p.bit_length()}-bit)")
    print(f"  q = {g.q}")
    print(f"    ({g.q.bit_length()}-bit, subgroup order)")
    print(f"  g = {g.g}")
    ok = is_safe_prime_group(g.p, g.q, g.g)
    print(f"  re-verified from scratch (Miller-Rabin on p and q, g^q == 1 mod p): {ok}")
    if not ok:
        print("FATAL: the standard group failed verification", file=sys.stderr)
        return 1
    if args.regenerate:
        print(f"\nSearching a fresh {args.bits}-bit safe-prime group (seed={args.seed})...")
        fresh = generate_safe_prime_group(bits=args.bits, seed=args.seed)
        print(f"  p = {fresh.p}")
        print(f"  q = {fresh.q}")
        print(f"  g = {fresh.g}")
    return 0


def cmd_schnorr_demo(args: argparse.Namespace) -> int:
    g = STANDARD_GROUP
    rng = _rng(args.seed)
    kp = S.generate_keypair(g, rng)
    print(f"Prover's secret x = {kp.x}")
    print(f"Public key y = g^x mod p = {kp.y}")

    print("\n-- Honest interactive proof --")
    tr = S.run_interactive_proof(g, kp, rng)
    print(f"  commitment t = {tr.t}")
    print(f"  challenge  c = {tr.c}")
    print(f"  response   s = {tr.s}")
    ok = S.verify(g, kp.y, tr.t, tr.c, tr.s)
    print(f"  verifier accepts: {ok}")
    if not ok:
        print("FATAL: honest proof rejected", file=sys.stderr)
        return 1

    print("\n-- Cheating prover (does not know x) --")
    wrong_x = (kp.x + 1) % g.q
    t2, r2 = S.commit(g, rng)
    c2 = S.challenge(g, rng)
    s2 = S.respond(g, wrong_x, r2, c2)
    cheat_ok = S.verify(g, kp.y, t2, c2, s2)
    print(f"  verifier accepts a proof with the wrong secret: {cheat_ok} (expected False)")
    if cheat_ok:
        print("FATAL: cheating prover was accepted", file=sys.stderr)
        return 1

    print("\n-- Special-soundness witness extraction --")
    print("  (two accepting transcripts, same commitment, different challenges)")
    t3, r3 = S.commit(g, rng)
    c3a = S.challenge(g, rng)
    s3a = S.respond(g, kp.x, r3, c3a)
    c3b = S.challenge(g, rng)
    while c3b == c3a:
        c3b = S.challenge(g, rng)
    s3b = S.respond(g, kp.x, r3, c3b)
    extracted = S.extract_witness(g, S.Transcript(t3, c3a, s3a), S.Transcript(t3, c3b, s3b))
    print(f"  extracted x = {extracted}")
    print(f"  matches real secret: {extracted == kp.x}")
    if extracted != kp.x:
        print("FATAL: extraction failed", file=sys.stderr)
        return 1
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    g = STANDARD_GROUP
    rng = _rng(args.seed)
    kp = FS.generate_keypair(g, rng)
    message = args.message.encode()
    sig = FS.sign(g, kp, message, rng)
    print(f"Public key: {kp.y}")
    print(f"Message: {args.message!r}")
    print(f"Signature: t={sig.t}, s={sig.s}")
    ok = FS.verify(g, kp.y, message, sig)
    print(f"Verifies: {ok}")
    if not ok:
        print("FATAL: valid signature rejected", file=sys.stderr)
        return 1

    tampered = (args.message + " [tampered]").encode()
    tamper_ok = FS.verify(g, kp.y, tampered, sig)
    print(f"Verifies against a tampered message: {tamper_ok} (expected False)")
    if tamper_ok:
        print("FATAL: tampered message accepted", file=sys.stderr)
        return 1
    return 0


def cmd_anon_auth(args: argparse.Namespace) -> int:
    g = STANDARD_GROUP
    rng = _rng(args.seed)
    if not (0 <= args.index < args.n):
        print(f"--index must be in [0, {args.n})", file=sys.stderr)
        return 2
    members = [S.generate_keypair(g, rng) for _ in range(args.n)]
    pubkeys = [m.y for m in members]
    print(f"Registered {args.n} members' public keys:")
    for i, y in enumerate(pubkeys):
        print(f"  member {i}: y = {y}")

    message = args.message.encode()
    proof = OR.prove_or(g, args.index, members[args.index].x, pubkeys, message, rng)
    print(f"\nAnonymous proof for message {args.message!r} (real signer index hidden)")
    ok = OR.verify_or(g, pubkeys, message, proof)
    print(f"Verifier accepts (member #{args.index} is proven to be SOME registered member): {ok}")
    if not ok:
        print("FATAL: valid OR-proof rejected", file=sys.stderr)
        return 1

    print("\n-- Outsider (not in the registered list) attempts to prove membership --")
    outsider = S.generate_keypair(g, rng)
    try:
        OR.prove_or(g, 0, outsider.x, pubkeys, message, rng)
        print("FATAL: outsider was able to construct a proof", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"  rejected at proof-construction time: {e}")
    return 0


def cmd_coloring_demo(args: argparse.Namespace) -> int:
    rng = _rng(args.seed)
    print(f"Graph: HOUSE_GRAPH ({C.HOUSE_GRAPH.num_vertices} vertices, {len(C.HOUSE_GRAPH.edges)} edges)")
    print(f"Prover's witness coloring: {C.HOUSE_COLORING} (kept secret from the verifier)")
    print(f"Witness is a valid 3-coloring: {C.is_valid_coloring(C.HOUSE_GRAPH, C.HOUSE_COLORING)}")

    print(f"\n-- Running {args.rounds} independent rounds --")
    transcripts = C.run_protocol(C.HOUSE_GRAPH, C.HOUSE_COLORING, args.rounds, rng)
    for i, t in enumerate(transcripts):
        u, v = C.HOUSE_GRAPH.edges[t.edge_index]
        print(
            f"  round {i}: verifier challenged edge ({u},{v}) -> revealed colors "
            f"({t.opening.color_u}, {t.opening.color_v}), accepted={t.accepted}"
        )
    all_accepted = all(t.accepted for t in transcripts)
    print(f"\nAll rounds accepted -> proof accepted: {all_accepted}")
    if not all_accepted:
        print("FATAL: an honest proof round was rejected", file=sys.stderr)
        return 1

    bound = C.soundness_error_bound(len(C.HOUSE_GRAPH.edges), args.rounds)
    print(
        f"Soundness: if the prover had no valid coloring, this many accepted rounds\n"
        f"would happen with probability at most {bound:.6g} "
        f"((1 - 1/{len(C.HOUSE_GRAPH.edges)})^{args.rounds})"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="veil", description="A from-scratch zero-knowledge proof toolkit.")
    sub = p.add_subparsers(dest="command", required=True)

    gi = sub.add_parser("group-info", help="Show and re-verify the Schnorr group parameters.")
    gi.add_argument("--regenerate", action="store_true", help="Also search a fresh safe-prime group.")
    gi.add_argument("--bits", type=int, default=64, help="Bit length for --regenerate (default 64, fast).")
    gi.add_argument("--seed", type=int, default=None, help="RNG seed.")
    gi.set_defaults(func=cmd_group_info)

    sd = sub.add_parser("schnorr", help="Run the Schnorr identification protocol end-to-end.")
    sd.add_argument("--seed", type=int, default=None)
    sd.set_defaults(func=cmd_schnorr_demo)

    sg = sub.add_parser("sign", help="Sign a message with a Fiat-Shamir/Schnorr signature.")
    sg.add_argument("message", type=str, help="Message to sign.")
    sg.add_argument("--seed", type=int, default=None)
    sg.set_defaults(func=cmd_sign)

    aa = sub.add_parser("anon-auth", help="Anonymous OR-proof membership authentication demo.")
    aa.add_argument("--n", type=int, default=5, help="Number of registered members.")
    aa.add_argument("--index", type=int, default=2, help="Which member is really signing (0-based).")
    aa.add_argument("--message", type=str, default="anonymous message")
    aa.add_argument("--seed", type=int, default=None)
    aa.set_defaults(func=cmd_anon_auth)

    cd = sub.add_parser("coloring", help="Graph 3-coloring zero-knowledge proof demo.")
    cd.add_argument("--rounds", type=int, default=20)
    cd.add_argument("--seed", type=int, default=None)
    cd.set_defaults(func=cmd_coloring_demo)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:  # noqa: BLE001 - CLI top-level error boundary
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
