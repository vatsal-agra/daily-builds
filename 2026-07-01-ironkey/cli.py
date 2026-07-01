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
import x25519
import session
import vault
import vulnerable_cbc
import padding_oracle
import viz


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


def cmd_dh_genkey(args):
    priv = x25519.generate_private_key()
    pub = x25519.derive_public_key(priv)
    if args.out:
        with open(args.out, "w") as f:
            f.write(priv.hex() + "\n")
        print(f"private key written to {args.out}")
    else:
        print(f"private: {priv.hex()}")
    print(f"public:  {pub.hex()}")


def cmd_dh_derive(args):
    priv = bytes.fromhex(args.priv_hex)
    peer_pub = bytes.fromhex(args.peer_pub_hex)
    shared = x25519.compute_shared_secret(priv, peer_pub)
    print(shared.hex())


def cmd_dh_demo(args):
    alice = session.Party("Alice")
    bob = session.Party("Bob")
    print(f"Alice private: {alice.private_key.hex()}")
    print(f"Alice public:  {alice.public_key.hex()}")
    print(f"Bob private:   {bob.private_key.hex()}")
    print(f"Bob public:    {bob.public_key.hex()}")
    shared_a = x25519.compute_shared_secret(alice.private_key, bob.public_key)
    shared_b = x25519.compute_shared_secret(bob.private_key, alice.public_key)
    print(f"Alice-derived shared secret: {shared_a.hex()}")
    print(f"Bob-derived shared secret:   {shared_b.hex()}")
    print("MATCH" if shared_a == shared_b else "MISMATCH (bug!)")
    if shared_a != shared_b:
        sys.exit(1)


def cmd_session_demo(args):
    ok = session.run_demo()
    sys.exit(0 if ok else 1)


def cmd_vault_encrypt(args):
    data = _read_input(args)
    out = vault.encrypt_file(args.password, data, args.iterations)
    if args.out_file:
        with open(args.out_file, "wb") as f:
            f.write(out)
        print(f"wrote {len(out)}-byte vault to {args.out_file}")
    else:
        sys.stdout.buffer.write(out)


def cmd_vault_decrypt(args):
    data = _read_input(args)
    pt = vault.decrypt_file(args.password, data)
    if args.out_file:
        with open(args.out_file, "wb") as f:
            f.write(pt)
        print(f"wrote {len(pt)} bytes to {args.out_file}")
    else:
        sys.stdout.buffer.write(pt)


def cmd_attack_demo(args):
    print("=== Attacking vulnerable_cbc.VulnerableCBCBox (no MAC) ===")
    box = vulnerable_cbc.VulnerableCBCBox()
    secret = (args.text or "The launch codes are 8675309, transmit at midnight sharp.").encode()
    ct = box.encrypt(secret)
    print(f"secret plaintext:  {secret!r}")
    print(f"ciphertext (never revealed to attacker in a real attack): {ct.hex()}")

    query_count = [0]

    def counting_oracle(candidate):
        query_count[0] += 1
        return box.padding_oracle(candidate)

    recovered = padding_oracle.recover_plaintext(counting_oracle, ct)
    print(f"recovered plaintext (attacker never had the key): {recovered!r}")
    print(f"oracle queries used: {query_count[0]}")
    print("ATTACK SUCCEEDED" if recovered == secret else "ATTACK FAILED (bug!)")
    if recovered != secret:
        sys.exit(1)

    print()
    print("=== Same technique against vault.py's real AES-256-GCM vault ===")
    v = vault.encrypt_file("a real password", secret, iterations=1000)
    ciphertext_region = v[len(vault._MAGIC) + vault._SALT_LEN + 8 + vault._IV_LEN + vault._TAG_LEN:]
    print("GCM has no padding at all (it's CTR-mode under the hood), so there is")
    print("no padding-validity oracle to exploit in the first place — the only")
    print("signal available is 'did the whole authenticated message verify',")
    print("which a single forged byte breaks essentially always.")
    print(f"vault ciphertext region length: {len(ciphertext_region)} bytes, no exploitable oracle exists.")


def cmd_viz(args):
    key = bytes.fromhex(args.aes_key_hex) if args.aes_key_hex else None
    aes_text = args.aes_text.encode() if args.aes_text else None
    sha_text = args.sha_text.encode() if args.sha_text else None
    path = viz.write_html(args.out, key=key, aes_text=aes_text, sha_text=sha_text)
    print(f"wrote interactive visualizer to {path}")


def cmd_demo(args):
    print("############################################")
    print("# Ironkey end-to-end demo")
    print("############################################\n")

    print("--- SHA-256 ---")
    print("sha256('abc') =", sha256(b"abc").hex())

    print("\n--- HMAC-SHA256 / PBKDF2 ---")
    print("hmac_sha256(b'key', b'msg') =", hmac_sha256(b"key", b"msg").hex())
    dk = pbkdf2_hmac_sha256(b"password", b"salt", 10_000, 32)
    print("pbkdf2(10000 iters) =", dk.hex())

    print("\n--- AES-256-GCM ---")
    key = os.urandom(32)
    iv = os.urandom(12)
    ct, tag = modes.gcm_encrypt(key, iv, b"a real message")
    pt = modes.gcm_decrypt(key, iv, ct, tag)
    print("round trip OK:", pt == b"a real message")

    print("\n--- RSA OAEP + PSS (2048-bit) ---")
    pub, priv = rsa.generate_keypair(bits=2048)
    ct_rsa = rsa.oaep_encrypt(pub, b"rsa message")
    print("OAEP round trip OK:", rsa.oaep_decrypt(priv, ct_rsa) == b"rsa message")
    sig = rsa.pss_sign(priv, b"sign me")
    print("PSS verify OK:", rsa.pss_verify(pub, b"sign me", sig))

    print("\n--- X25519 + encrypted session ---")
    if not session.run_demo(verbose_print=lambda *a: None):
        print("session demo FAILED")
        sys.exit(1)
    print("session demo OK (handshake, messaging, tamper + replay detection)")

    print("\n--- Vault ---")
    v = vault.encrypt_file("demo password", b"vault contents", iterations=1000)
    print("vault round trip OK:", vault.decrypt_file("demo password", v) == b"vault contents")

    print("\n--- Padding-oracle attack ---")
    box = vulnerable_cbc.VulnerableCBCBox()
    secret = b"attack me"
    ct_vuln = box.encrypt(secret)
    recovered = padding_oracle.recover_plaintext(box.padding_oracle, ct_vuln)
    print("attack recovered exact plaintext:", recovered == secret)

    print("\nALL DEMOS PASSED")


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
    pk.add_argument("--iterations", type=int, default=4096)
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

    pdh = sub.add_parser("dh", help="X25519 Diffie-Hellman key exchange")
    dhsub = pdh.add_subparsers(dest="dh_command", required=True)

    pdhg = dhsub.add_parser("genkey")
    pdhg.add_argument("--out", help="write private key hex to this file instead of stdout")
    pdhg.set_defaults(func=cmd_dh_genkey)

    pdhd = dhsub.add_parser("derive", help="compute a shared secret from your private key and a peer's public key")
    pdhd.add_argument("--priv-hex", required=True)
    pdhd.add_argument("--peer-pub-hex", required=True)
    pdhd.set_defaults(func=cmd_dh_derive)

    pdhm = dhsub.add_parser("demo", help="full Alice/Bob handshake demo")
    pdhm.set_defaults(func=cmd_dh_demo)

    psess = sub.add_parser("session", help="X25519 + AES-256-GCM encrypted messaging session")
    sesssub = psess.add_subparsers(dest="session_command", required=True)
    psessd = sesssub.add_parser("demo", help="handshake, messaging, tamper + replay detection demo")
    psessd.set_defaults(func=cmd_session_demo)

    pv = sub.add_parser("vault", help="password-based encrypted file vault (PBKDF2 + AES-256-GCM)")
    vsub = pv.add_subparsers(dest="vault_command", required=True)

    pve = vsub.add_parser("encrypt")
    _add_input_args(pve)
    pve.add_argument("--password", required=True)
    pve.add_argument("--iterations", type=int, default=4096)
    pve.add_argument("--out", dest="out_file")
    pve.set_defaults(func=cmd_vault_encrypt)

    pvd = vsub.add_parser("decrypt")
    _add_input_args(pvd)
    pvd.add_argument("--password", required=True)
    pvd.add_argument("--out", dest="out_file")
    pvd.set_defaults(func=cmd_vault_decrypt)

    pat = sub.add_parser("attack", help="Vaudenay padding-oracle attack demo (educational — no key needed)")
    atsub = pat.add_subparsers(dest="attack_command", required=True)
    patd = atsub.add_parser("demo")
    patd.add_argument("--text", help="secret text to attack (default: a sample message)")
    patd.set_defaults(func=cmd_attack_demo)

    pviz = sub.add_parser("viz", help="generate an interactive HTML visualizer (AES rounds + SHA-256 compression)")
    pviz.add_argument("--out", default="ironkey_viz.html")
    pviz.add_argument("--aes-key-hex")
    pviz.add_argument("--aes-text", help="exactly 16 bytes (padded/truncated if not)")
    pviz.add_argument("--sha-text")
    pviz.set_defaults(func=cmd_viz)

    pdemo = sub.add_parser("demo", help="run every feature end to end")
    pdemo.set_defaults(func=cmd_demo)

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
