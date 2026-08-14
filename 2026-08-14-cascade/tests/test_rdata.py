import pytest

from cascade import rdata
from cascade.name import Name, DNSFormatError


def _roundtrip(rd, rtype):
    buf = bytearray()
    rd.encode(buf, {})
    decoder = rdata.DECODERS[rtype]
    decoded = decoder(bytes(buf), 0, len(buf))
    return decoded


def test_a_record():
    rd = rdata.A("93.184.216.34")
    assert _roundtrip(rd, 1) == rd
    buf = bytearray()
    rd.encode(buf, {})
    assert len(buf) == 4


def test_aaaa_record():
    rd = rdata.AAAA("2001:db8::1")
    assert _roundtrip(rd, 28) == rd


def test_a_rejects_wrong_length():
    with pytest.raises(DNSFormatError):
        rdata.A.decode(b"\x01\x02\x03", 0, 3)


def test_ns_cname_ptr():
    n = Name.from_text("ns1.example.com.")
    assert _roundtrip(rdata.NS(n), 2) == rdata.NS(n)
    assert _roundtrip(rdata.CNAME(n), 5) == rdata.CNAME(n)
    assert _roundtrip(rdata.PTR(n), 12) == rdata.PTR(n)


def test_mx():
    rd = rdata.MX(10, Name.from_text("mail.example.com."))
    assert _roundtrip(rd, 15) == rd


def test_txt_multi_string():
    rd = rdata.TXT((b"hello", b"world"))
    assert _roundtrip(rd, 16) == rd


def test_txt_empty_defaults_to_single_empty_string():
    rd = rdata.TXT(())
    buf = bytearray()
    rd.encode(buf, {})
    assert bytes(buf) == b"\x00"  # one zero-length character-string


def test_txt_rejects_oversized_character_string():
    with pytest.raises(DNSFormatError):
        rdata.TXT((b"x" * 256,)).encode(bytearray(), {})


def test_soa():
    rd = rdata.SOA(
        Name.from_text("ns1.example.com."), Name.from_text("hostmaster.example.com."),
        2026081401, 3600, 900, 604800, 3600,
    )
    assert _roundtrip(rd, 6) == rd


def test_rdlength_mismatch_detected():
    # An NS rdata claiming a different length than it actually consumed
    # (e.g. a corrupted/lying RDLENGTH) must raise, not silently misparse.
    buf = bytearray()
    rdata.NS(Name.from_text("ns.example.com.")).encode(buf, {})
    with pytest.raises(DNSFormatError):
        rdata.NS.decode(bytes(buf), 0, len(buf) - 1)
    with pytest.raises(DNSFormatError):
        rdata.NS.decode(bytes(buf), 0, len(buf) + 1)


def test_unknown_type_falls_back_to_raw():
    from cascade.rdata import decode_rdata
    raw = decode_rdata(9999, b"\x01\x02\x03\x04", 0, 4)
    assert raw.data == b"\x01\x02\x03\x04"
