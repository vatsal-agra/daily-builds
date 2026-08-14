"""Differential testing against `dnspython` -- a real, independent,
spec-compliant DNS library -- as an external oracle for Cascade's wire
codec, the same "verify against a real independent implementation" pattern
this repo uses elsewhere (real `git`, `gcc`/`objdump`, Node's WASM engine,
NLTK, `sqlite3`, ...). `dnspython` is a dev/test-only dependency: it is
never imported by anything under `cascade/`, and this whole module skips
cleanly if it isn't installed rather than failing the suite.
"""

import random

import pytest

dns = pytest.importorskip("dns.message")
import dns.rdataclass
import dns.rdatatype

from cascade import rdata
from cascade.consts import (
    TYPE_A, TYPE_AAAA, TYPE_NS, TYPE_CNAME, TYPE_MX, TYPE_TXT, TYPE_SOA, TYPE_PTR, CLASS_IN,
)
from cascade.message import DNSMessage, Question, RR
from cascade.name import Name

TYPES = [TYPE_A, TYPE_AAAA, TYPE_NS, TYPE_CNAME, TYPE_MX, TYPE_TXT, TYPE_SOA, TYPE_PTR]
TLDS = ["com.", "net.", "org.", "x.y.z."]


def _rand_name(rng):
    n = rng.randint(1, 4)
    labels = ["".join(rng.choice("abcdefghij0123-") for _ in range(rng.randint(1, 10))) for _ in range(n)]
    return Name.from_text(".".join(labels) + "." + rng.choice(TLDS))


def _rand_rdata(rng, rtype):
    if rtype == TYPE_A:
        return rdata.A(f"{rng.randint(0,255)}.{rng.randint(0,255)}.{rng.randint(0,255)}.{rng.randint(0,255)}")
    if rtype == TYPE_AAAA:
        return rdata.AAAA("2001:db8::" + ":".join(f"{rng.randint(0,0xffff):x}" for _ in range(2)))
    if rtype == TYPE_NS:
        return rdata.NS(_rand_name(rng))
    if rtype == TYPE_CNAME:
        return rdata.CNAME(_rand_name(rng))
    if rtype == TYPE_MX:
        return rdata.MX(rng.randint(0, 65535), _rand_name(rng))
    if rtype == TYPE_TXT:
        return rdata.TXT(tuple(
            bytes(rng.randint(32, 126) for _ in range(rng.randint(0, 50)))
            for _ in range(rng.randint(1, 3))
        ))
    if rtype == TYPE_SOA:
        return rdata.SOA(_rand_name(rng), _rand_name(rng), rng.randint(0, 2**32 - 1),
                          rng.randint(0, 10000), rng.randint(0, 10000), rng.randint(0, 10000),
                          rng.randint(0, 10000))
    if rtype == TYPE_PTR:
        return rdata.PTR(_rand_name(rng))
    raise AssertionError(rtype)


def test_fuzz_cascade_encoded_messages_parse_cleanly_in_dnspython():
    # 1,000 random-but-valid messages (at most one RRset per (name, type) --
    # anything else isn't valid DNS in the first place, see REVIEW.md's note
    # on the first, invalid-data version of this fuzz run).
    rng = random.Random(7)
    total_checked = 0
    for _ in range(1000):
        msg = DNSMessage(id=rng.randint(0, 65535), qr=True, aa=True)
        qname = _rand_name(rng)
        msg.questions = [Question(qname, TYPE_A)]
        shared_names = [_rand_name(rng) for _ in range(3)]
        used = set()
        sent = []
        for _ in range(rng.randint(0, 8)):
            rtype = rng.choice(TYPES)
            name = rng.choice(shared_names + [qname])
            key = (name, rtype)
            if key in used:
                continue
            used.add(key)
            rr = RR(name, rtype, CLASS_IN, rng.randint(1, 100000), _rand_rdata(rng, rtype))
            sent.append(rr)
            msg.answers.append(rr)

        wire = msg.to_wire()
        parsed = dns.message.from_wire(wire)  # must not raise
        total = sum(len(rrset) for rrset in parsed.answer)
        assert total == len(sent)
        for rr in sent:
            assert any(
                rrset.name.to_text() == rr.name.to_text() and rrset.rdtype == rr.rtype
                for rrset in parsed.answer
            ), f"record {rr} missing from dnspython's parse"

        back = DNSMessage.from_wire(wire)
        assert len(back.answers) == len(sent)
        total_checked += 1
    assert total_checked == 1000


def test_dnspython_encoded_query_decodes_correctly_in_cascade():
    q = dns.message.make_query("www.example.com.", "A")
    ours = DNSMessage.from_wire(q.to_wire())
    assert ours.questions[0].qname.to_text() == "www.example.com."
    assert ours.questions[0].qtype == TYPE_A


def test_cascade_soa_rdata_matches_dnspython_field_for_field():
    rd = rdata.SOA(Name.from_text("ns1.example.com."), Name.from_text("hostmaster.example.com."),
                    2026081401, 3600, 900, 604800, 3600)
    msg = DNSMessage(id=1, qr=True, aa=True)
    msg.questions = [Question(Name.from_text("example.com."), TYPE_SOA)]
    msg.answers = [RR(Name.from_text("example.com."), TYPE_SOA, CLASS_IN, 3600, rd)]
    parsed = dns.message.from_wire(msg.to_wire())
    dnspy_soa = parsed.answer[0][0]
    assert str(dnspy_soa.mname) == "ns1.example.com."
    assert str(dnspy_soa.rname) == "hostmaster.example.com."
    assert dnspy_soa.serial == 2026081401
    assert dnspy_soa.refresh == 3600
    assert dnspy_soa.retry == 900
    assert dnspy_soa.expire == 604800
    assert dnspy_soa.minimum == 3600
