#!/usr/bin/env python3
"""
Ironkey command-line interface — every primitive and application in this
suite is reachable from here. Run `./cli.py <subcommand> -h` for details,
or `./cli.py demo` to exercise everything end to end.
"""
import argparse
import os
import sys

from sha256 import sha256
from hmac_kdf import hmac_sha256, pbkdf2_hmac_sha256
import modes
import rsa


def _read_input(args):
    if getattr(args, "text", None) is not None:
        return args.text.encode()
    if getattr(args, "in_file", None):
        with open(args.in_file, "rb") as f:
            return f.read()
    return sys.stdin.buffer.read()


def cmd_hash(args):
    data = _read_input(args)
    print(sha256(data).hex())


def cmd_hmac(args):
    key = bytes.fromhex(args.key_hex) if args.key_hex else args.key.encode()
    data = _read_input(args)
    print(hmac_sha256(key, data).hex())


def cmd_kdf(args):
    salt = bytes.fromhex(args.salt_hex) if args.salt_hex else os.urandom(16)
    dk = pbkdf2_hmac_sha256(args.password.encode(), salt, args.iterations, args.dklen)
    print(f"salt={salt.hex()}")
    print(f"iterations={args.iterations}")
    print(f"key={dk.hex()}")


def cmd_aes_encrypt(args):
    key = bytes.fromhex(args.key_hex)
    data = _read_input(args)
    if args.mode == "cbc":
        iv = os.urandom(16)
        ct = modes.cbc_encrypt(key, iv, data)
        out = iv + ct
    else:
        iv = os.urandom(12)
        aad = args.aad.encode() if args.aad else b""
        ct, tag = modes.gcm_encrypt(key, iv, data, aad)
        out = iv + tag + ct
    if args.out_file:
        with open(args.out_file, "wb") as f:
            f.write(out)
        print(f"wrote {len(out)} bytes to {args.out_file} (iv{'+ tag' if args.mode == 'gcm' else ''} prepended)")
    else:
        sys.stdout.buffer.write(out)


def cmd_aes_decrypt(args):
    key = bytes.fromhex(args.key_hex)
    data = _read_input(args)
    if args.mode == "cbc":
        iv, ct = data[:16], data[16:]
        pt = modes.cbc_decrypt(key, iv, ct)
    else:
        iv, tag, ct = data[:12], data[12:28], data[28:]
        aad = args.aad.encode() if args.aad else b""
        pt = modes.gcm_decrypt(key, iv, ct, tag, aad)
    if args.out_file:
        with open(args.out_file, "wb") as f:
            f.write(pt)
        print(f"wrote {len(pt)} bytes to {args.out_file}")
    else:
        sys.stdout.buffer.write(pt)


def cmd_rsa_genkey(args):
    pub, priv = rsa.generate_keypair(bits=args.bits)
    rsa.save_public_key(pub, args.pub_out)
    rsa.save_private_key(priv, args.priv_out)
    print(f"generated {args.bits}-bit RSA keypair -> {args.pub_out}, {args.priv_out}")


def cmd_rsa_encrypt(args):
    pub = rsa.load_public_key(args.pub)
    data = _read_input(args)
    ct = rsa.oaep_encrypt(pub, data)
    if args.out_file:
        with open(args.out_file, "wb") as f:
            f.write(ct)
        print(f"wrote {len(ct)}-byte ciphertext to {args.out_file}")
    else:
        sys.stdout.buffer.write(ct)


def cmd_rsa_decrypt(args):
    priv = rsa.load_private_key(args.priv)
    data = _read_input(args)
    pt = rsa.oaep_decrypt(priv, data)
    if args.out_file:
        with open(args.out_file, "wb") as f:
            f.write(pt)
        print(f"wrote {len(pt)} bytes to {args.out_file}")
    else:
        sys.stdout.buffer.write(pt)


def cmd_rsa_sign(args):
    priv = rsa.load_private_key(args.priv)
    data = _read_input(args)
    sig = rsa.pss_sign(priv, data)
    if args.out_file:
        with open(args.out_file, "wb") as f:
            f.write(sig)
        print(f"wrote {len(sig)}-byte signature to {args.out_file}")
    else:
        print(sig.hex())


def cmd_rsa_verify(args):
    pub = rsa.load_public_key(args.pub)
    data = _read_input(args)
    with open(args.sig, "rb") as f:
        sig = f.read()
    ok = rsa.pss_verify(pub, data, sig)
    print("VALID" if ok else "INVALID")
    sys.exit(0 if ok else 1)


def _add_input_args(p, required_text=False):
    g = p.add_mutually_exclusive_group(required=required_text)
    g.add_argument("--text", help="literal text input")
    g.add_argument("--in", dest="in_file", help="input file path")


def build_parser():
    p = argparse.ArgumentParser(prog="ironkey", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    ph = sub.add_parser("hash", help="SHA-256 a file or literal text")
    _add_input_args(ph)
    ph.set_defaults(func=cmd_hash)

    pm = sub.add_parser("hmac", help="HMAC-SHA256 a file or literal text")
    _add_input_args(pm)
    g = pm.add_mutually_exclusive_group(required=True)
    g.add_argument("--key", help="key as literal text")
    g.add_argument("--key-hex", help="key as hex bytes")
    pm.set_defaults(func=cmd_hmac)

    pk = sub.add_parser("kdf", help="derive a key from a password with PBKDF2-HMAC-SHA256")
    pk.add_argument("--password", required=True)
    pk.add_argument("--salt-hex", help="hex salt (random 16 bytes if omitted)")
    pk.add_argument("--iterations", type=int, default=200_000)
    pk.add_argument("--dklen", type=int, default=32)
    pk.set_defaults(func=cmd_kdf)

    pa = sub.add_parser("aes", help="AES-256 encrypt/decrypt (CBC or GCM)")
    asub = pa.add_subparsers(dest="aes_command", required=True)

    pae = asub.add_parser("encrypt")
    _add_input_args(pae)
    pae.add_argument("--key-hex", required=True, help="16/24/32-byte AES key, hex")
    pae.add_argument("--mode", choices=["cbc", "gcm"], default="gcm")
    pae.add_argument("--aad", help="associated data (GCM only)")
    pae.add_argument("--out", dest="out_file")
    pae.set_defaults(func=cmd_aes_encrypt)

    pad = asub.add_parser("decrypt")
    _add_input_args(pad)
    pad.add_argument("--key-hex", required=True)
    pad.add_argument("--mode", choices=["cbc", "gcm"], default="gcm")
    pad.add_argument("--aad", help="associated data (GCM only)")
    pad.add_argument("--out", dest="out_file")
    pad.set_defaults(func=cmd_aes_decrypt)

    pr = sub.add_parser("rsa", help="RSA key generation, OAEP encryption, PSS signatures")
    rsub = pr.add_subparsers(dest="rsa_command", required=True)

    prg = rsub.add_parser("genkey")
    prg.add_argument("--bits", type=int, default=2048)
    prg.add_argument("--pub-out", default="rsa_pub.json")
    prg.add_argument("--priv-out", default="rsa_priv.json")
    prg.set_defaults(func=cmd_rsa_genkey)

    pre = rsub.add_parser("encrypt")
    _add_input_args(pre)
    pre.add_argument("--pub", required=True)
    pre.add_argument("--out", dest="out_file")
    pre.set_defaults(func=cmd_rsa_encrypt)

    prd = rsub.add_parser("decrypt")
    _add_input_args(prd)
    prd.add_argument("--priv", required=True)
    prd.add_argument("--out", dest="out_file")
    prd.set_defaults(func=cmd_rsa_decrypt)

    prs = rsub.add_parser("sign")
    _add_input_args(prs)
    prs.add_argument("--priv", required=True)
    prs.add_argument("--out", dest="out_file")
    prs.set_defaults(func=cmd_rsa_sign)

    prv = rsub.add_parser("verify")
    _add_input_args(prv)
    prv.add_argument("--pub", required=True)
    prv.add_argument("--sig", required=True)
    prv.set_defaults(func=cmd_rsa_verify)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
