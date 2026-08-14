"""Per-type RDATA encode/decode (RFC 1035 section 3.3, RFC 3596 for AAAA).

Each record type gets a small immutable dataclass plus an `encode`/`decode`
pair. Encoders append raw bytes to a shared message buffer (so that domain
names embedded in rdata -- NS/CNAME/MX/SOA/PTR -- can participate in the
*same* message-wide compression table as every other name, exactly like a
real nameserver). Decoders read from a shared buffer at an absolute offset
for the same reason: a compressed name inside rdata can point anywhere
earlier in the whole message, not just within the rdata itself.
"""

from __future__ import annotations

import ipaddress
import struct
from dataclasses import dataclass

from .consts import (
    TYPE_A, TYPE_AAAA, TYPE_NS, TYPE_CNAME, TYPE_SOA, TYPE_PTR, TYPE_MX, TYPE_TXT,
)
from .name import Name, encode_name, decode_name, DNSFormatError


def _check_consumed(type_name: str, rdata_start: int, end: int, rdlength: int) -> None:
    """Verify a name-bearing rdata consumed exactly rdlength physical bytes.

    This catches both a corrupt/lying RDLENGTH field and any encoder bug
    where compression made a name shorter or longer than declared.
    """
    consumed = end - rdata_start
    if consumed != rdlength:
        raise DNSFormatError(
            f"{type_name} rdata declared {rdlength} bytes but consumed {consumed}"
        )


@dataclass(frozen=True)
class A:
    address: str  # dotted-quad IPv4 text

    def encode(self, buf: bytearray, compression: dict | None) -> None:
        buf.extend(ipaddress.IPv4Address(self.address).packed)

    @staticmethod
    def decode(buf: bytes, offset: int, rdlength: int) -> "A":
        if rdlength != 4:
            raise DNSFormatError(f"A record rdata must be 4 bytes, got {rdlength}")
        return A(str(ipaddress.IPv4Address(bytes(buf[offset:offset + 4]))))


@dataclass(frozen=True)
class AAAA:
    address: str  # IPv6 text

    def encode(self, buf: bytearray, compression: dict | None) -> None:
        buf.extend(ipaddress.IPv6Address(self.address).packed)

    @staticmethod
    def decode(buf: bytes, offset: int, rdlength: int) -> "AAAA":
        if rdlength != 16:
            raise DNSFormatError(f"AAAA record rdata must be 16 bytes, got {rdlength}")
        return AAAA(str(ipaddress.IPv6Address(bytes(buf[offset:offset + 16]))))


@dataclass(frozen=True)
class NS:
    nsdname: Name

    def encode(self, buf: bytearray, compression: dict | None) -> None:
        encode_name(self.nsdname, buf, compression)

    @staticmethod
    def decode(buf: bytes, offset: int, rdlength: int) -> "NS":
        name, end = decode_name(buf, offset)
        _check_consumed("NS", offset, end, rdlength)
        return NS(name)


@dataclass(frozen=True)
class CNAME:
    cname: Name

    def encode(self, buf: bytearray, compression: dict | None) -> None:
        encode_name(self.cname, buf, compression)

    @staticmethod
    def decode(buf: bytes, offset: int, rdlength: int) -> "CNAME":
        name, end = decode_name(buf, offset)
        _check_consumed("CNAME", offset, end, rdlength)
        return CNAME(name)


@dataclass(frozen=True)
class PTR:
    ptrdname: Name

    def encode(self, buf: bytearray, compression: dict | None) -> None:
        encode_name(self.ptrdname, buf, compression)

    @staticmethod
    def decode(buf: bytes, offset: int, rdlength: int) -> "PTR":
        name, end = decode_name(buf, offset)
        _check_consumed("PTR", offset, end, rdlength)
        return PTR(name)


@dataclass(frozen=True)
class MX:
    preference: int
    exchange: Name

    def encode(self, buf: bytearray, compression: dict | None) -> None:
        buf.extend(struct.pack("!H", self.preference))
        encode_name(self.exchange, buf, compression)

    @staticmethod
    def decode(buf: bytes, offset: int, rdlength: int) -> "MX":
        if rdlength < 2:
            raise DNSFormatError(f"MX record rdata too short ({rdlength} bytes)")
        (preference,) = struct.unpack("!H", buf[offset:offset + 2])
        name, end = decode_name(buf, offset + 2)
        _check_consumed("MX", offset, end, rdlength)
        return MX(preference, name)


@dataclass(frozen=True)
class TXT:
    strings: tuple  # tuple[bytes, ...] -- each a single character-string (<=255 bytes)

    def encode(self, buf: bytearray, compression: dict | None) -> None:
        strings = self.strings if self.strings else (b"",)
        for s in strings:
            if len(s) > 255:
                raise DNSFormatError("TXT character-string longer than 255 bytes")
            buf.append(len(s))
            buf.extend(s)

    @staticmethod
    def decode(buf: bytes, offset: int, rdlength: int) -> "TXT":
        end = offset + rdlength
        strings = []
        cur = offset
        while cur < end:
            length = buf[cur]
            cur += 1
            if cur + length > end:
                raise DNSFormatError("TXT character-string extends past rdlength")
            strings.append(bytes(buf[cur:cur + length]))
            cur += length
        return TXT(tuple(strings))


@dataclass(frozen=True)
class SOA:
    mname: Name
    rname: Name
    serial: int
    refresh: int
    retry: int
    expire: int
    minimum: int

    def encode(self, buf: bytearray, compression: dict | None) -> None:
        encode_name(self.mname, buf, compression)
        encode_name(self.rname, buf, compression)
        buf.extend(struct.pack("!IIIII", self.serial, self.refresh, self.retry,
                                self.expire, self.minimum))

    @staticmethod
    def decode(buf: bytes, offset: int, rdlength: int) -> "SOA":
        mname, off = decode_name(buf, offset)
        rname, off = decode_name(buf, off)
        if off + 20 > len(buf):
            raise DNSFormatError("SOA record rdata truncated")
        serial, refresh, retry, expire, minimum = struct.unpack("!IIIII", buf[off:off + 20])
        end = off + 20
        _check_consumed("SOA", offset, end, rdlength)
        return SOA(mname, rname, serial, refresh, retry, expire, minimum)


# Fallback for any RR type we don't have a structured class for: keep the
# raw bytes so the message can still round-trip losslessly.
@dataclass(frozen=True)
class RAW:
    data: bytes

    def encode(self, buf: bytearray, compression: dict | None) -> None:
        buf.extend(self.data)

    @staticmethod
    def decode(buf: bytes, offset: int, rdlength: int) -> "RAW":
        return RAW(bytes(buf[offset:offset + rdlength]))


DECODERS = {
    TYPE_A: A.decode, TYPE_AAAA: AAAA.decode, TYPE_NS: NS.decode,
    TYPE_CNAME: CNAME.decode, TYPE_SOA: SOA.decode, TYPE_PTR: PTR.decode,
    TYPE_MX: MX.decode, TYPE_TXT: TXT.decode,
}


def decode_rdata(rtype: int, buf: bytes, offset: int, rdlength: int):
    decoder = DECODERS.get(rtype, RAW.decode)
    return decoder(buf, offset, rdlength)
