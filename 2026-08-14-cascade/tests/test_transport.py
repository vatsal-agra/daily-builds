import time

import pytest

from cascade import rdata, transport
from cascade.consts import TYPE_A, TYPE_TXT, CLASS_IN
from cascade.message import DNSMessage, Question, RR
from cascade.name import Name
from cascade.server import AuthoritativeServer
from cascade.zonefile import Zone


@pytest.fixture
def live_zone():
    text = """
$TTL 3600
$ORIGIN t.
@         IN SOA ns1.t. hostmaster.t. (1 3600 900 604800 3600)
@         IN NS  ns1.t.
ns1.t.    IN A   127.0.0.70
host      IN A   1.2.3.4
"""
    zone = Zone.from_text(text, Name.from_text("t."))
    srv = AuthoritativeServer({zone.origin: zone}, "127.0.0.70", 5460)
    srv.start()
    time.sleep(0.2)
    try:
        yield zone, srv
    finally:
        srv.stop()


def test_udp_query_basic(live_zone):
    zone, srv = live_zone
    msg = DNSMessage(id=1, rd=False)
    msg.questions = [Question(Name.from_text("host.t."), TYPE_A)]
    resp = transport.udp_query(msg, "127.0.0.70", 5460, timeout=2.0)
    assert resp.answers[0].rdata.address == "1.2.3.4"


def test_query_times_out_on_unreachable_server():
    msg = DNSMessage(id=1, rd=False)
    msg.questions = [Question(Name.from_text("host.t."), TYPE_A)]
    with pytest.raises(transport.QueryTimeout):
        transport.udp_query(msg, "127.0.0.70", 5461, timeout=0.3)  # nobody listening on .461


def test_response_id_mismatch_detected(live_zone, monkeypatch):
    # Simulate a spoofed/stale response by asking with one ID and pretending
    # we expected a different one.
    zone, srv = live_zone
    msg = DNSMessage(id=1, rd=False)
    msg.questions = [Question(Name.from_text("host.t."), TYPE_A)]
    real_resp = transport.udp_query(msg, "127.0.0.70", 5460, timeout=2.0)
    fake_query = DNSMessage(id=real_resp.id + 1, rd=False)  # claim we expected a different ID
    fake_query.questions = list(msg.questions)
    with pytest.raises(transport.QueryError):
        transport._validate(real_resp, fake_query, "127.0.0.70", 5460)


def test_auto_tcp_retry_on_truncation(live_zone):
    zone, srv = live_zone
    big_name = Name.from_text("big.t.")
    zone.records[big_name] = [RR(big_name, TYPE_TXT, CLASS_IN, 300,
                                  rdata.TXT(tuple(b"x" * 200 for _ in range(8))))]
    msg = DNSMessage(id=1, rd=False)
    msg.questions = [Question(big_name, TYPE_TXT)]

    plain = transport.udp_query(msg, "127.0.0.70", 5460, timeout=2.0)
    assert plain.tc

    complete = transport.query(msg, "127.0.0.70", 5460, timeout=2.0)  # should auto-retry via TCP
    assert not complete.tc
    assert len(complete.answers[0].rdata.strings) == 8
