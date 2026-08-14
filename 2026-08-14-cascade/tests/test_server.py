import time

import pytest

from cascade.consts import (
    TYPE_A, TYPE_AAAA, TYPE_CNAME, TYPE_MX, TYPE_NS, TYPE_TXT,
    RCODE_NOERROR, RCODE_NXDOMAIN, RCODE_SERVFAIL,
)
from cascade.message import DNSMessage, Question
from cascade.name import Name
from cascade.server import AuthoritativeServer, answer_in_zone, build_response
from cascade.zonefile import Zone
from cascade import transport
import cascade.server as servermod


@pytest.fixture
def test_zone():
    text = """
$TTL 3600
$ORIGIN test.
@                IN SOA ns1.test. hostmaster.test. (1 3600 900 604800 3600)
@                IN NS  ns1.test.
ns1.test.        IN A   127.0.0.50
@                IN A   1.2.3.4
@                IN AAAA 2001:db8::1
@                IN MX  10 mail.test.
mail.test.       IN A   1.2.3.5
www              IN CNAME @
alias-of-alias   IN CNAME www.test.
*.wild           IN A   9.9.9.9
a.b              IN A   8.8.8.8
sub.test.        IN NS  ns1.sub.test.
ns1.sub.test.    IN A   127.0.0.51
"""
    return Zone.from_text(text, Name.from_text("test."))


def _query(zone, name, qtype):
    resp = DNSMessage(id=1, rd=False)
    resp.questions = [Question(Name.from_text(name), qtype)]
    return build_response({zone.origin: zone}, resp)


def test_exact_match(test_zone):
    resp = _query(test_zone, "test.", TYPE_A)
    assert resp.aa and resp.rcode == RCODE_NOERROR
    assert resp.answers[0].rdata.address == "1.2.3.4"


def test_aaaa(test_zone):
    resp = _query(test_zone, "test.", TYPE_AAAA)
    assert resp.answers[0].rdata.address == "2001:db8::1"


def test_cname_chase_within_zone(test_zone):
    resp = _query(test_zone, "www.test.", TYPE_A)
    rtypes = [r.rtype for r in resp.answers]
    assert rtypes == [TYPE_CNAME, TYPE_A]
    assert resp.answers[1].rdata.address == "1.2.3.4"


def test_double_cname_chase(test_zone):
    resp = _query(test_zone, "alias-of-alias.test.", TYPE_A)
    rtypes = [r.rtype for r in resp.answers]
    assert rtypes == [TYPE_CNAME, TYPE_CNAME, TYPE_A]


def test_cname_record_itself_not_chased_when_requested(test_zone):
    resp = _query(test_zone, "www.test.", TYPE_CNAME)
    assert len(resp.answers) == 1
    assert resp.answers[0].rtype == TYPE_CNAME


def test_mx(test_zone):
    resp = _query(test_zone, "test.", TYPE_MX)
    assert resp.answers[0].rdata.preference == 10


def test_nxdomain(test_zone):
    resp = _query(test_zone, "totally-absent.test.", TYPE_A)
    assert resp.rcode == RCODE_NXDOMAIN
    assert resp.authority and resp.authority[0].rtype == 6  # SOA for negative caching


def test_nodata(test_zone):
    resp = _query(test_zone, "test.", TYPE_TXT)  # exists, but has no TXT
    assert resp.rcode == RCODE_NOERROR
    assert not resp.answers
    assert resp.authority and resp.authority[0].rtype == 6


def test_wildcard(test_zone):
    resp = _query(test_zone, "anything.wild.test.", TYPE_A)
    assert resp.answers[0].name.to_text() == "anything.wild.test."
    assert resp.answers[0].rdata.address == "9.9.9.9"


def test_wildcard_does_not_override_empty_non_terminal(test_zone):
    # Regression test for REVIEW.md #1: 'b.test.' has no data of its own,
    # but 'a.b.test.' exists beneath it, so 'b.test.' is a real empty
    # non-terminal node and must get NODATA, not a match against some
    # unrelated wildcard.
    resp = _query(test_zone, "b.test.", TYPE_A)
    assert resp.rcode == RCODE_NOERROR
    assert not resp.answers


def test_delegation_referral_with_glue(test_zone):
    resp = _query(test_zone, "host.sub.test.", TYPE_A)
    assert not resp.aa
    assert any(r.rtype == TYPE_NS for r in resp.authority)
    assert any(r.rdata.address == "127.0.0.51" for r in resp.additional)


def test_delegation_point_itself_is_referred(test_zone):
    resp = _query(test_zone, "sub.test.", TYPE_NS)
    assert not resp.aa  # even querying the exact delegation point is a referral, not an authoritative answer


def test_apex_not_treated_as_delegation(test_zone):
    resp = _query(test_zone, "test.", TYPE_NS)
    assert resp.aa
    assert resp.answers


def test_refused_for_unrelated_zone(test_zone):
    q = DNSMessage(id=1, rd=False)
    q.questions = [Question(Name.from_text("totally.unrelated.org."), TYPE_A)]
    resp = build_response({test_zone.origin: test_zone}, q)
    assert resp.rcode == 5  # REFUSED


def test_formerr_on_multiple_questions(test_zone):
    q = DNSMessage(id=1, rd=False)
    q.questions = [Question(Name.from_text("test."), TYPE_A), Question(Name.from_text("test."), TYPE_MX)]
    resp = build_response({test_zone.origin: test_zone}, q)
    assert resp.rcode == 1  # FORMERR


# --- live server: real sockets ---------------------------------------------

def test_server_survives_internal_bug_and_returns_servfail(test_zone, monkeypatch):
    # Regression test for REVIEW.md #2: an internal bug answering one query
    # must not kill the listener for every future client.
    srv = AuthoritativeServer({test_zone.origin: test_zone}, "127.0.0.60", 5450)
    srv.start()
    time.sleep(0.2)
    try:
        def buggy(*a, **kw):
            raise KeyError("simulated bug")
        monkeypatch.setattr(servermod, "answer_in_zone", buggy)

        msg = DNSMessage(id=1, rd=False)
        msg.questions = [Question(Name.from_text("test."), TYPE_A)]
        resp = transport.udp_query(msg, "127.0.0.60", 5450, timeout=2.0)
        assert resp.rcode == RCODE_SERVFAIL

        monkeypatch.undo()
        msg2 = DNSMessage(id=2, rd=False)
        msg2.questions = [Question(Name.from_text("test."), TYPE_A)]
        resp2 = transport.udp_query(msg2, "127.0.0.60", 5450, timeout=2.0)
        assert resp2.rcode == RCODE_NOERROR
        assert resp2.answers
    finally:
        srv.stop()


def test_tcp_query_works(test_zone):
    srv = AuthoritativeServer({test_zone.origin: test_zone}, "127.0.0.61", 5451)
    srv.start()
    time.sleep(0.2)
    try:
        msg = DNSMessage(id=1, rd=False)
        msg.questions = [Question(Name.from_text("test."), TYPE_A)]
        resp = transport.tcp_query(msg, "127.0.0.61", 5451, timeout=2.0)
        assert resp.answers[0].rdata.address == "1.2.3.4"
    finally:
        srv.stop()


def test_malformed_udp_packet_is_dropped_not_crashed(test_zone):
    import socket
    srv = AuthoritativeServer({test_zone.origin: test_zone}, "127.0.0.62", 5452)
    srv.start()
    time.sleep(0.2)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.5)
        sock.sendto(b"\xff\xff\xff", ("127.0.0.62", 5452))  # garbage, too short to be a header
        with pytest.raises(socket.timeout):
            sock.recvfrom(65535)  # server should silently drop it, no response
        sock.close()
        # server must still be alive afterwards
        msg = DNSMessage(id=1, rd=False)
        msg.questions = [Question(Name.from_text("test."), TYPE_A)]
        resp = transport.udp_query(msg, "127.0.0.62", 5452, timeout=2.0)
        assert resp.answers
    finally:
        srv.stop()


def test_bind_failure_does_not_leak_udp_socket(test_zone):
    srv1 = AuthoritativeServer({test_zone.origin: test_zone}, "127.0.0.63", 5453)
    srv1.start()
    time.sleep(0.1)
    try:
        srv2 = AuthoritativeServer({test_zone.origin: test_zone}, "127.0.0.63", 5453)
        with pytest.raises(OSError):
            srv2.start()
        assert srv2._udp_sock is None  # cleaned up, not leaked (REVIEW.md #2)
    finally:
        srv1.stop()
