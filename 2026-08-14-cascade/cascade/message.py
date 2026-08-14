"""RFC 1035 message framing: header + question + answer/authority/additional,
plus RFC 6891 EDNS0 (the OPT pseudo-RR).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .consts import CLASS_IN, TYPE_OPT, EDNS_UDP_MAX
from .name import Name, ROOT, encode_name, decode_name, DNSFormatError

HEADER_LEN = 12


@dataclass(frozen=True)
class Question:
    qname: Name
    qtype: int
    qclass: int = CLASS_IN


@dataclass(frozen=True)
class RR:
    name: Name
    rtype: int
    rclass: int
    ttl: int
    rdata: object


@dataclass(frozen=True)
class EDNSOptions:
    udp_payload_size: int = EDNS_UDP_MAX
    extended_rcode: int = 0
    version: int = 0
    do: bool = False
    options: tuple = ()

    def encode(self, buf: bytearray) -> None:
        encode_name(ROOT, buf, None)
        buf += struct.pack("!H", TYPE_OPT)
        buf += struct.pack("!H", self.udp_payload_size)
        ttl = ((self.extended_rcode & 0xFF) << 24) | ((self.version & 0xFF) << 16)
        if self.do:
            ttl |= 0x8000
        buf += struct.pack("!I", ttl)
        rdata = bytearray()
        for code, data in self.options:
            rdata += struct.pack("!HH", code, len(data)) + data
        buf += struct.pack("!H", len(rdata)) + rdata

    @staticmethod
    def decode(rclass: int, ttl: int, buf: bytes, rdata_start: int, rdlength: int) -> "EDNSOptions":
        udp_size = rclass
        extended_rcode = (ttl >> 24) & 0xFF
        version = (ttl >> 16) & 0xFF
        do = bool(ttl & 0x8000)
        opts = []
        p = rdata_start
        end = rdata_start + rdlength
        while p < end:
            if p + 4 > end:
                raise DNSFormatError("truncated EDNS option header")
            code, length = struct.unpack("!HH", buf[p:p + 4])
            p += 4
            if p + length > end:
                raise DNSFormatError("EDNS option data extends past rdata")
            opts.append((code, bytes(buf[p:p + length])))
            p += length
        return EDNSOptions(udp_size, extended_rcode, version, do, tuple(opts))


def _encode_rr(rr: RR, buf: bytearray, compression: dict) -> None:
    encode_name(rr.name, buf, compression)
    buf += struct.pack("!HHI", rr.rtype, rr.rclass, rr.ttl & 0xFFFFFFFF)
    rdlen_pos = len(buf)
    buf += b"\x00\x00"
    start = len(buf)
    rr.rdata.encode(buf, compression)
    rdlen = len(buf) - start
    if rdlen > 0xFFFF:
        raise DNSFormatError("rdata too long to encode (>65535 bytes)")
    buf[rdlen_pos:rdlen_pos + 2] = struct.pack("!H", rdlen)


def _decode_one_rr(buf: bytes, offset: int):
    """Returns (RR | ('edns', EDNSOptions), new_offset)."""
    name, offset = decode_name(buf, offset)
    if offset + 10 > len(buf):
        raise DNSFormatError("truncated resource record header")
    rtype, rclass, ttl, rdlength = struct.unpack("!HHIH", buf[offset:offset + 10])
    offset += 10
    if offset + rdlength > len(buf):
        raise DNSFormatError("rdata extends past end of message")
    rdata_start = offset
    if rtype == TYPE_OPT:
        edns = EDNSOptions.decode(rclass, ttl, buf, rdata_start, rdlength)
        return ("edns", edns), offset + rdlength
    from .rdata import decode_rdata
    rdata_obj = decode_rdata(rtype, buf, rdata_start, rdlength)
    return RR(name, rtype, rclass, ttl, rdata_obj), offset + rdlength


def _decode_section(buf: bytes, offset: int, count: int):
    items = []
    for _ in range(count):
        item, offset = _decode_one_rr(buf, offset)
        items.append(item)
    return items, offset


@dataclass
class DNSMessage:
    id: int
    qr: bool = False
    opcode: int = 0
    aa: bool = False
    tc: bool = False
    rd: bool = True
    ra: bool = False
    ad: bool = False
    cd: bool = False
    rcode: int = 0
    questions: list = field(default_factory=list)
    answers: list = field(default_factory=list)
    authority: list = field(default_factory=list)
    additional: list = field(default_factory=list)
    edns: EDNSOptions | None = None

    @property
    def effective_rcode(self) -> int:
        """The combined 12-bit RCODE (RFC 6891 6.1.3) when EDNS0 is present."""
        if self.edns is None:
            return self.rcode
        return (self.edns.extended_rcode << 4) | (self.rcode & 0xF)

    def _build(self, answers, authority, additional, tc: bool) -> bytearray:
        buf = bytearray()
        flags = 0
        if self.qr:
            flags |= 1 << 15
        flags |= (self.opcode & 0xF) << 11
        if self.aa:
            flags |= 1 << 10
        if tc:
            flags |= 1 << 9
        if self.rd:
            flags |= 1 << 8
        if self.ra:
            flags |= 1 << 7
        if self.ad:
            flags |= 1 << 5
        if self.cd:
            flags |= 1 << 4
        flags |= self.rcode & 0xF
        arcount = len(additional) + (1 if self.edns is not None else 0)
        buf += struct.pack(
            "!HHHHHH", self.id, flags,
            len(self.questions), len(answers), len(authority), arcount,
        )
        compression: dict = {}
        for q in self.questions:
            encode_name(q.qname, buf, compression)
            buf += struct.pack("!HH", q.qtype, q.qclass)
        for section in (answers, authority, additional):
            for rr in section:
                _encode_rr(rr, buf, compression)
        if self.edns is not None:
            self.edns.encode(buf)
        return buf

    def to_wire(self, max_size: int | None = None) -> bytes:
        """Encode to wire format.

        If `max_size` is given and the full message doesn't fit, RRs are
        dropped from the end of additional, then authority, then answer
        (never partially -- a record is either whole or absent) and the TC
        bit is set, matching real truncation behavior.
        """
        answers, authority, additional = self.answers, self.authority, self.additional
        # Seed from self.tc (not a hardcoded False): truncation here can
        # only ever *set* TC, never silently clear a caller-set one. Found
        # by Phase 5's flag round-trip test -- see REVIEW.md #7.
        tc = self.tc
        while True:
            buf = self._build(answers, authority, additional, tc)
            if max_size is None or len(buf) <= max_size:
                return bytes(buf)
            tc = True
            if additional:
                additional = additional[:-1]
            elif authority:
                authority = authority[:-1]
            elif answers:
                answers = answers[:-1]
            else:
                # Even a bare header+question(s)+EDNS doesn't fit. Nothing
                # more can be dropped; return it truncated anyway rather
                # than loop forever.
                return bytes(buf)

    @staticmethod
    def from_wire(buf: bytes) -> "DNSMessage":
        if len(buf) < HEADER_LEN:
            raise DNSFormatError(f"message too short to contain a header ({len(buf)} bytes)")
        msg_id, flags, qdcount, ancount, nscount, arcount = struct.unpack("!HHHHHH", buf[:HEADER_LEN])
        qr = bool(flags & (1 << 15))
        opcode = (flags >> 11) & 0xF
        aa = bool(flags & (1 << 10))
        tc = bool(flags & (1 << 9))
        rd = bool(flags & (1 << 8))
        ra = bool(flags & (1 << 7))
        ad = bool(flags & (1 << 5))
        cd = bool(flags & (1 << 4))
        rcode = flags & 0xF

        offset = HEADER_LEN
        questions = []
        for _ in range(qdcount):
            name, offset = decode_name(buf, offset)
            if offset + 4 > len(buf):
                raise DNSFormatError("truncated question")
            qtype, qclass = struct.unpack("!HH", buf[offset:offset + 4])
            offset += 4
            questions.append(Question(name, qtype, qclass))

        answers, offset = _decode_section(buf, offset, ancount)
        authority, offset = _decode_section(buf, offset, nscount)
        additional_raw, offset = _decode_section(buf, offset, arcount)

        additional = []
        edns = None
        for item in additional_raw:
            if isinstance(item, tuple) and item[0] == "edns":
                edns = item[1]
            else:
                additional.append(item)

        return DNSMessage(
            id=msg_id, qr=qr, opcode=opcode, aa=aa, tc=tc, rd=rd, ra=ra,
            ad=ad, cd=cd, rcode=rcode, questions=questions, answers=answers,
            authority=authority, additional=additional, edns=edns,
        )
