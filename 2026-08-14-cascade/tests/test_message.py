from cascade import rdata
from cascade.consts import TYPE_A, TYPE_NS, TYPE_MX, CLASS_IN
from cascade.message import DNSMessage, Question, RR, EDNSOptions
from cascade.name import Name


def _sample_message():
    msg = DNSMessage(id=0xABCD, qr=True, aa=True, rd=True, ra=False)
    msg.questions = [Question(Name.from_text("www.example.com."), TYPE_A)]
    msg.answers = [RR(Name.from_text("www.example.com."), TYPE_A, CLASS_IN, 300, rdata.A("1.2.3.4"))]
    msg.authority = [RR(Name.from_text("example.com."), TYPE_NS, CLASS_IN, 300,
                         rdata.NS(Name.from_text("ns1.example.com.")))]
    msg.additional = [RR(Name.from_text("ns1.example.com."), TYPE_A, CLASS_IN, 300, rdata.A("5.6.7.8"))]
    return msg


def test_roundtrip_all_sections():
    msg = _sample_message()
    wire = msg.to_wire()
    back = DNSMessage.from_wire(wire)
    assert back.id == msg.id
    assert back.qr and back.aa and back.rd and not back.ra
    assert back.questions == msg.questions
    assert back.answers == msg.answers
    assert back.authority == msg.authority
    assert back.additional == msg.additional


def test_flag_bits_independent():
    for qr in (True, False):
        for aa in (True, False):
            for tc in (True, False):
                for rd in (True, False):
                    for ra in (True, False):
                        msg = DNSMessage(id=1, qr=qr, aa=aa, tc=tc, rd=rd, ra=ra)
                        back = DNSMessage.from_wire(msg.to_wire())
                        assert (back.qr, back.aa, back.tc, back.rd, back.ra) == (qr, aa, tc, rd, ra)


def test_opcode_and_rcode_roundtrip():
    msg = DNSMessage(id=1, opcode=2, rcode=5)
    back = DNSMessage.from_wire(msg.to_wire())
    assert back.opcode == 2
    assert back.rcode == 5


def test_edns_roundtrip():
    msg = DNSMessage(id=1, edns=EDNSOptions(udp_payload_size=4096, do=True))
    msg.questions = [Question(Name.from_text("example.com."), TYPE_A)]
    wire = msg.to_wire()
    back = DNSMessage.from_wire(wire)
    assert back.edns is not None
    assert back.edns.udp_payload_size == 4096
    assert back.edns.do is True
    assert back.additional == []  # OPT must not leak into the real additional list


def test_message_without_edns_has_no_opt_record():
    msg = DNSMessage(id=1)
    msg.questions = [Question(Name.from_text("example.com."), TYPE_A)]
    back = DNSMessage.from_wire(msg.to_wire())
    assert back.edns is None


def test_truncation_sets_tc_and_drops_whole_records_only():
    msg = _sample_message()
    # add enough extra answers to guarantee we exceed a small cap
    for i in range(20):
        msg.answers.append(RR(Name.from_text(f"host{i}.example.com."), TYPE_A, CLASS_IN, 300,
                               rdata.A(f"10.0.0.{i}")))
    full_wire = msg.to_wire()
    capped = msg.to_wire(max_size=200)
    assert len(capped) <= 200
    back = DNSMessage.from_wire(capped)
    assert back.tc is True
    # every record that did survive must be byte-identical/whole -- i.e. it
    # parses cleanly with no leftover/partial trailing bytes
    assert len(full_wire) > len(capped)


def test_truncation_never_drops_edns_opt():
    msg = DNSMessage(id=1, edns=EDNSOptions(udp_payload_size=4096))
    msg.questions = [Question(Name.from_text("example.com."), TYPE_A)]
    for i in range(30):
        msg.answers.append(RR(Name.from_text(f"host{i}.example.com."), TYPE_A, CLASS_IN, 300,
                               rdata.A("1.2.3.4")))
    capped = msg.to_wire(max_size=150)
    back = DNSMessage.from_wire(capped)
    assert back.tc is True
    assert back.edns is not None  # OPT survives even when real answers get dropped


def test_compression_makes_repeated_names_cheap():
    msg = DNSMessage(id=1, qr=True, aa=True)
    msg.questions = [Question(Name.from_text("example.com."), TYPE_A)]
    for i in range(10):
        msg.answers.append(RR(Name.from_text("example.com."), TYPE_MX, CLASS_IN, 300,
                               rdata.MX(i, Name.from_text("example.com."))))
    wire = msg.to_wire()
    uncompressed_estimate = 10 * (len(b"\x07example\x03com\x00") * 2 + 12)
    assert len(wire) < uncompressed_estimate
    back = DNSMessage.from_wire(wire)
    assert len(back.answers) == 10
