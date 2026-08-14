import pytest

from cascade.name import Name, ROOT, DNSFormatError, encode_name, decode_name


def test_from_text_to_text_roundtrip():
    assert Name.from_text("www.example.com.").to_text() == "www.example.com."
    assert Name.from_text("www.example.com").to_text() == "www.example.com."  # trailing dot optional
    assert Name.from_text(".").to_text() == "."
    assert Name.from_text("").to_text() == "."


def test_case_insensitive_equality_and_hash():
    a = Name.from_text("WWW.Example.COM.")
    b = Name.from_text("www.example.com.")
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1
    # but the original case is preserved for display/wire purposes
    assert a.labels[0] == b"WWW"


def test_is_subdomain_of():
    root = Name.from_text(".")
    com = Name.from_text("com.")
    example_com = Name.from_text("example.com.")
    www_example_com = Name.from_text("www.example.com.")
    assert com.is_subdomain_of(root)
    assert example_com.is_subdomain_of(com)
    assert www_example_com.is_subdomain_of(example_com)
    assert www_example_com.is_subdomain_of(root)
    assert example_com.is_subdomain_of(example_com)  # a name is its own subdomain
    assert not com.is_subdomain_of(example_com)
    assert not Name.from_text("evilexample.com.").is_subdomain_of(example_com)


def test_relativize_and_parent():
    origin = Name.from_text("example.com.")
    name = Name.from_text("www.example.com.")
    assert name.relativize(origin).to_text() == "www."
    assert name.parent().to_text() == "example.com."
    with pytest.raises(ValueError):
        Name.from_text("other.org.").relativize(origin)


def test_label_and_name_length_limits():
    with pytest.raises(DNSFormatError):
        Name((b"a" * 64,))  # single label over 63 bytes
    # 4 labels of 50 bytes = 4*(50+1)+1 = 205 wire bytes: right at the edge, still valid.
    near_limit = Name.from_text(".".join(["a" * 50] * 4) + ".")
    assert near_limit is not None
    # A 5th 50-byte label pushes it to 256 wire bytes, over the 255 cap.
    with pytest.raises(DNSFormatError):
        Name(near_limit.labels + (b"a" * 50,))


def test_empty_label_rejected():
    with pytest.raises(DNSFormatError):
        Name.from_text("bad..name.com.")


# --- wire format: encode/decode + compression -----------------------------

def test_simple_roundtrip_no_compression():
    name = Name.from_text("www.example.com.")
    buf = bytearray()
    encode_name(name, buf, None)
    decoded, offset = decode_name(bytes(buf), 0)
    assert decoded == name
    assert offset == len(buf)


def test_compression_reuses_suffix():
    buf = bytearray()
    compression = {}
    n1 = Name.from_text("www.example.com.")
    n2 = Name.from_text("mail.example.com.")
    encode_name(n1, buf, compression)
    pos2 = len(buf)
    encode_name(n2, buf, compression)
    # n2 should end with a 2-byte pointer back into n1's "example.com." suffix,
    # not a second full copy of those labels.
    assert len(buf) - pos2 == len(b"\x04mail") + 2
    d1, _ = decode_name(bytes(buf), 0)
    d2, _ = decode_name(bytes(buf), pos2)
    assert d1 == n1
    assert d2 == n2


def test_compression_is_case_insensitive():
    buf = bytearray()
    compression = {}
    encode_name(Name.from_text("WWW.EXAMPLE.COM."), buf, compression)
    pos2 = len(buf)
    encode_name(Name.from_text("mail.example.com."), buf, compression)
    assert len(buf) - pos2 == len(b"\x04mail") + 2  # still compressed despite case difference


def test_rfc1035_4_1_4_worked_example():
    # The structure of the worked example from RFC 1035 section 4.1.4:
    # F.ISI.ARPA, FOO.F.ISI.ARPA, and ARPA sharing suffixes via compression
    # pointers, laid out starting at offset 20 like the RFC figure.
    buf = bytearray(20)  # pad so our first name starts at offset 20, like the RFC figure
    compression = {}
    encode_name(Name.from_text("F.ISI.ARPA."), buf, compression)
    pos_foo = len(buf)
    encode_name(Name.from_text("FOO.F.ISI.ARPA."), buf, compression)
    pos_arpa = len(buf)
    encode_name(Name.from_text("ARPA."), buf, compression)
    pos_root = len(buf)
    encode_name(ROOT, buf, compression)

    n1, _ = decode_name(bytes(buf), 20)
    n2, _ = decode_name(bytes(buf), pos_foo)
    n3, _ = decode_name(bytes(buf), pos_arpa)
    n4, _ = decode_name(bytes(buf), pos_root)
    assert n1 == Name.from_text("F.ISI.ARPA.")
    assert n2 == Name.from_text("FOO.F.ISI.ARPA.")
    assert n3 == Name.from_text("ARPA.")
    assert n4 == ROOT
    # FOO.F.ISI.ARPA must compress against F.ISI.ARPA: "FOO" (4 bytes) + a
    # 2-byte pointer, not a second full copy of ".F.ISI.ARPA".
    assert pos_arpa - pos_foo == len(b"\x03FOO") + 2


def test_decode_rejects_forward_pointer_and_self_pointer():
    # A pointer that points at or after itself can never terminate legitimately.
    buf = bytearray(b"\x00" * 4)
    buf[0] = 0xC0
    buf[1] = 0x00  # points at offset 0, i.e. at itself
    with pytest.raises(DNSFormatError):
        decode_name(bytes(buf), 0)


def test_decode_rejects_pointer_loop():
    # offset 0: pointer -> 2 ; offset 2: pointer -> 0  (mutual loop)
    buf = bytearray(4)
    buf[0], buf[1] = 0xC0, 0x02
    buf[2], buf[3] = 0xC0, 0x00
    with pytest.raises(DNSFormatError):
        decode_name(bytes(buf), 0)


def test_decode_truncated_name_raises():
    with pytest.raises(DNSFormatError):
        decode_name(b"\x05abc", 0)  # claims a 5-byte label but only 3 bytes follow
