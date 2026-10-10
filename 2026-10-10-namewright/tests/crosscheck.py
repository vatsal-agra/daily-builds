#!/usr/bin/env python3
"""Cross-check Namewright against dnspython, an independent DNS implementation.

Run:  python3 -I tests/crosscheck.py   (needs: pip install dnspython cryptography)
Starts the mini internet itself (needs the built binary at $NAMEWRIGHT or ./namewright).

Direction 1 (Namewright -> dnspython): dnspython parses our wire output, validates our
DNSSEC signatures/DS digests/NSEC chain, and compares the zone parser's output.
Direction 2 (dnspython -> Namewright): a zone signed by dnspython must verify in
`namewright verify`; a message built by dnspython must decode in our codec.
"""
import os, subprocess, sys, tempfile, time, re, socket, struct

import dns.dnssec, dns.flags, dns.message, dns.name, dns.query, dns.rcode, dns.rdatatype, dns.zone, dns.rdataclass
import dns.rdata
from cryptography.hazmat.primitives.asymmetric import ed25519, ec

BIN = os.environ.get("NAMEWRIGHT", "./namewright")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures, checks = [], 0

def check(cond, what):
    global checks
    checks += 1
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        failures.append(what)

def start_testnet(*flags):
    p = subprocess.Popen([BIN, "testnet", *flags, "-listen", "127.0.0.1:0"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    hosts, front = {}, None
    deadline = time.time() + 10
    while time.time() < deadline:
        line = p.stdout.readline()
        m = re.match(r"\s+(\S+)\s+\S+\s+-> (127\.0\.0\.1:\d+)", line)
        if m:
            hosts[m.group(1)] = m.group(2)
        m = re.search(r"listening on (127\.0\.0\.1:\d+)", line)
        if m:
            front = m.group(1)
            break
    assert front, "testnet did not start"
    return p, hosts, front

def hp(addr):
    h, p = addr.rsplit(":", 1)
    return h, int(p)

def q(addr, name, rdtype, want_dnssec=False, rd=False):
    m = dns.message.make_query(name, rdtype, want_dnssec=want_dnssec, use_edns=0, payload=4096)
    if rd:
        m.flags |= dns.flags.RD
    else:
        m.flags &= ~dns.flags.RD
    h, p = hp(addr)
    return dns.query.udp_with_fallback(m, h, port=p, timeout=5)[0]

def main():
    print("== direction 1: Namewright output validated by dnspython")
    p, hosts, front = start_testnet("-signed")
    try:
        ex, com, root = hosts["ns1.example.com"], hosts["a.gtld-servers.net"], hosts["a.root-servers.net"]
        # --- wire format
        r = q(ex, "www2.example.com.", "A")
        check(r.rcode() == dns.rcode.NOERROR and r.flags & dns.flags.AA, "dnspython parses authoritative CNAME-chain answer, AA set")
        check([str(x.name) for x in r.answer] == ["www2.example.com.", "www.example.com.", "web.example.com."], "answer chain order")
        r = q(ex, "example.com.", "ANY")
        types = {dns.rdatatype.to_text(rs.rdtype) for rs in r.answer}
        check({"SOA", "NS", "MX", "TXT", "CAA"} <= types, f"ANY returns all apex RRsets {sorted(types)}")
        r = q(ex, "nope.example.com.", "A")
        check(r.rcode() == dns.rcode.NXDOMAIN and r.authority and r.authority[0].rdtype == dns.rdatatype.SOA, "NXDOMAIN + SOA")
        r = q(ex, "big.example.com.", "TXT")  # UDP+TCP fallback path
        check(len(r.answer[0]) == 10, "TC -> TCP fallback gives all 10 TXT strings")
        r = q(com, "www.example.com.", "A")
        check(not (r.flags & dns.flags.AA) and r.authority[0].rdtype == dns.rdatatype.NS and r.additional, "referral: no AA, NS + glue")

        # --- DNSSEC: signatures
        def fetch(addr, name, t):
            return q(addr, name, t, want_dnssec=True)
        dk = fetch(ex, "example.com.", "DNSKEY")
        keys = {dns.name.from_text("example.com."): dk.find_rrset(dk.answer, dns.name.from_text("example.com."), dns.rdataclass.IN, dns.rdatatype.DNSKEY)}
        sig = dk.find_rrset(dk.answer, dns.name.from_text("example.com."), dns.rdataclass.IN, dns.rdatatype.RRSIG, dns.rdatatype.DNSKEY)
        try:
            dns.dnssec.validate(keys[dns.name.from_text("example.com.")], sig, keys); ok = True
        except Exception as e:
            ok = False; print("   ", e)
        check(ok, "dnspython validates our DNSKEY self-signature (Ed25519)")
        for name, t, srv, zone in [("web.example.com.", "A", ex, "example.com."), ("example.com.", "SOA", ex, "example.com."),
                                    ("www.example.com.", "NSEC", ex, "example.com."), ("example.com.", "MX", ex, "example.com.")]:
            m = fetch(srv, name, t)
            rr = m.find_rrset(m.answer, dns.name.from_text(name), dns.rdataclass.IN, dns.rdatatype.from_text(t))
            sg = m.find_rrset(m.answer, dns.name.from_text(name), dns.rdataclass.IN, dns.rdatatype.RRSIG, dns.rdatatype.from_text(t))
            try:
                dns.dnssec.validate(rr, sg, keys); ok = True
            except Exception as e:
                ok = False; print("   ", e)
            check(ok, f"dnspython validates our RRSIG over {name} {t}")
        # wildcard expansion (RRSIG labels field handling)
        m = fetch(ex, "zzz.dev.example.com.", "A")
        rr = m.find_rrset(m.answer, dns.name.from_text("zzz.dev.example.com."), dns.rdataclass.IN, dns.rdatatype.A)
        sg = m.find_rrset(m.answer, dns.name.from_text("zzz.dev.example.com."), dns.rdataclass.IN, dns.rdatatype.RRSIG, dns.rdatatype.A)
        try:
            dns.dnssec.validate(rr, sg, keys); ok = True
        except Exception as e:
            ok = False; print("   ", e)
        check(ok, "dnspython validates a wildcard-synthesised answer's RRSIG")
        # ECDSA zone (com.)
        dkc = fetch(com, "com.", "DNSKEY")
        ckeys = {dns.name.from_text("com."): dkc.find_rrset(dkc.answer, dns.name.from_text("com."), dns.rdataclass.IN, dns.rdatatype.DNSKEY)}
        sgc = dkc.find_rrset(dkc.answer, dns.name.from_text("com."), dns.rdataclass.IN, dns.rdatatype.RRSIG, dns.rdatatype.DNSKEY)
        try:
            dns.dnssec.validate(ckeys[dns.name.from_text("com.")], sgc, ckeys); ok = True
        except Exception as e:
            ok = False; print("   ", e)
        check(ok, "dnspython validates our ECDSA-P256 DNSKEY self-signature (com.)")
        # --- DS digests: dnspython recomputes DS from DNSKEY and must equal what com. serves
        ds = fetch(com, "example.com.", "DS")
        ds_rr = ds.find_rrset(ds.answer, dns.name.from_text("example.com."), dns.rdataclass.IN, dns.rdatatype.DS)
        ds_rd = ds_rr[0]
        match = False
        for k in keys[dns.name.from_text("example.com.")]:
            if k.flags & 1:  # SEP
                mine = dns.dnssec.make_ds("example.com.", k, "SHA256")
                match = mine == ds_rd
        check(match, "DS served by com. equals dnspython's DS(SHA-256) of example.com's KSK")
        # --- signed denial of existence is syntactically what dnspython expects
        nx = fetch(ex, "nope.example.com.", "A")
        nsecs = [rs for rs in nx.authority if rs.rdtype == dns.rdatatype.NSEC]
        check(len(nsecs) >= 1 and all(isinstance(rd.next, dns.name.Name) for rs in nsecs for rd in rs), "NSEC records decode in dnspython")

        # --- recursive front end with AD bit
        r = q(front, "web.example.com.", "A", want_dnssec=True, rd=True)
        check(bool(r.flags & dns.flags.AD) and r.rcode() == dns.rcode.NOERROR, "validating recursor sets AD for a secure answer")
        r = q(front, "host.sub.example.com.", "A", want_dnssec=True, rd=True)
        check(not (r.flags & dns.flags.AD) and r.rcode() == dns.rcode.NOERROR, "AD clear for an insecure delegation")
    finally:
        p.terminate(); p.wait()

    print("== zone parser vs dnspython")
    for z in ["example.com", "sub.example.com", "glueless.com", "dnshost.net", "com", "net", "root"]:
        path = f"{ROOT}/miniverse/internet/{z}.zone"
        origin = "." if z == "root" else z + "."
        theirs = dns.zone.from_file(path, origin=origin, relativize=False)
        want = sorted(f"{n} {rs.ttl} IN {dns.rdatatype.to_text(rs.rdtype)} {rd.to_text()}".replace("\t", " ")
                      for n, node in theirs.nodes.items() for rs in node.rdatasets for rd in rs)
        out = subprocess.run([BIN, "check", "-print", "-origin", origin, path], capture_output=True, text=True).stdout
        got = sorted(l.replace("\t", " ") for l in out.splitlines() if not l.startswith("zone "))
        check(got == want, f"zone {z}: {len(want)} records identical to dnspython's parse")

    print("== direction 2: dnspython output consumed by Namewright")
    # a dnspython-signed zone (Ed25519 and ECDSA) must verify in `namewright verify`
    for algname, mk in [("ED25519", lambda: ed25519.Ed25519PrivateKey.generate()), ("ECDSAP256SHA256", lambda: ec.generate_private_key(ec.SECP256R1()))]:
        text = "$TTL 300\n@ IN SOA ns hostmaster 1 3600 600 86400 120\n@ IN NS ns\nns IN A 192.0.2.1\nwww IN A 192.0.2.2\nmail IN MX 10 www\n*.wild IN A 192.0.2.9\n"
        zone = dns.zone.from_text(text, origin="signed.test.", relativize=False)
        priv = mk()
        pubkey = dns.dnssec.make_dnskey(priv.public_key(), getattr(dns.dnssec.Algorithm, algname), flags=257)
        dns.dnssec.sign_zone(zone, keys=[(dns.dnssec.Key if False else priv, pubkey)] if False else [(priv, pubkey)], add_dnskey=True, dnskey_ttl=300, nsec3=None, lifetime=86400 * 7)
        with tempfile.NamedTemporaryFile("w", suffix=".zone", delete=False) as f:
            f.write(zone.to_text()); path = f.name
        res = subprocess.run([BIN, "verify", "-origin", "signed.test.", path], capture_output=True, text=True)
        check(res.returncode == 0, f"namewright verifies a dnspython-signed {algname} zone ({res.stdout.strip()[:80] or res.stderr.strip()[:80]})")
        os.unlink(path)
    # dnspython-built messages decode in our codec (round trip via `namewright decode`)
    m = dns.message.make_query("www.example.com.", "AAAA", use_edns=0, want_dnssec=True, payload=1232)
    resp = dns.message.make_response(m)
    resp.answer.append(dns.rrset.from_text("www.example.com.", 60, "IN", "AAAA", "2001:db8::1", "2001:db8::2"))
    resp.answer.append(dns.rrset.from_text("www.example.com.", 60, "IN", "TXT", '"a b" "c\\"d"'))
    resp.authority.append(dns.rrset.from_text("example.com.", 60, "IN", "SOA", "ns.example.com. h.example.com. 1 2 3 4 5"))
    out = subprocess.run([BIN, "decode"], input=resp.to_wire().hex(), capture_output=True, text=True)
    check(out.returncode == 0 and "2001:db8::2" in out.stdout and '"c\\"d"' in out.stdout, "our decoder reads a dnspython-encoded response")
    # and what we re-encode is read back identically by dnspython
    lines = [l for l in out.stdout.splitlines() if l.startswith("wire:")]
    if lines:
        back = dns.message.from_wire(bytes.fromhex(lines[0].split()[1]))
        check(back.answer == resp.answer and back.authority == resp.authority, "dnspython reads our re-encoding identically")
    else:
        check(False, "decode printed no re-encoded wire")

    print(f"\n{checks - len(failures)}/{checks} cross-checks passed")
    return 1 if failures else 0

if __name__ == "__main__":
    sys.exit(main())
