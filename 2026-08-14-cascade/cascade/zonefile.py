"""A BIND-style master zone file parser, plus the in-memory `Zone` this
project's authoritative server answers queries out of.

Supports: $ORIGIN, $TTL, TTL inheritance from the previous record (or $TTL),
comments (`;`), parenthesized multi-line records (for SOA), relative and
`@`-relative names, and the record types Cascade implements (SOA, NS, A,
AAAA, CNAME, MX, TXT, PTR). Not attempted: $INCLUDE, $GENERATE, DNSSEC RR
types, and the full RFC-1034-general wildcard-matching algorithm (Zone below
implements the common single-label wildcard case; see REVIEW.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import rdata
from .consts import (
    TYPE_A, TYPE_AAAA, TYPE_NS, TYPE_CNAME, TYPE_SOA, TYPE_PTR, TYPE_MX, TYPE_TXT,
    NAME_TO_TYPE, CLASS_IN,
)
from .message import RR
from .name import Name, DNSFormatError

RRTYPE_WORDS = {"A", "AAAA", "NS", "CNAME", "SOA", "MX", "TXT", "PTR"}
CLASS_WORDS = {"IN"}


class ZoneFileError(Exception):
    pass


def _strip_comment(line: str) -> str:
    out = []
    in_quotes = False
    for c in line:
        if c == '"':
            in_quotes = not in_quotes
            out.append(c)
        elif c == ";" and not in_quotes:
            break
        else:
            out.append(c)
    return "".join(out)


def _paren_delta(line: str) -> int:
    """Net '(' minus ')' count, ignoring both inside a quoted string -- a
    literal paren in a TXT string must not be treated as a line-continuation
    marker."""
    delta = 0
    in_quotes = False
    for c in line:
        if c == '"':
            in_quotes = not in_quotes
        elif not in_quotes:
            if c == "(":
                delta += 1
            elif c == ")":
                delta -= 1
    return delta


def _strip_parens_outside_quotes(text: str) -> str:
    """Replace '(' and ')' with spaces, except inside a quoted string.
    (Found by adversarial review -- see REVIEW.md #3: the previous
    blanket `.replace()` silently deleted parens from TXT record data.)"""
    out = []
    in_quotes = False
    for c in text:
        if c == '"':
            in_quotes = not in_quotes
            out.append(c)
        elif c in "()" and not in_quotes:
            out.append(" ")
        else:
            out.append(c)
    return "".join(out)


def _logical_lines(text: str):
    """Yield (logical_line, owner_field_present) pairs, joining parenthesized
    continuations and dropping comments/blank lines. `owner_field_present` is
    True iff the *first* physical line of the group had no leading whitespace
    (BIND convention: a line starting in column 0 supplies an owner name; an
    indented line inherits the previous record's owner)."""
    lines = []
    buf = []
    depth = 0
    starts_unindented = None
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not buf:
            starts_unindented = bool(line.strip()) and not line[:1].isspace()
        depth += _paren_delta(line)
        if depth < 0:
            raise ZoneFileError(f"unbalanced parenthesis: {raw!r}")
        buf.append(line)
        if depth == 0:
            logical = _strip_parens_outside_quotes(" ".join(buf))
            if logical.strip():
                lines.append((logical, bool(starts_unindented)))
            buf = []
    if buf and any(b.strip() for b in buf):
        raise ZoneFileError("unterminated parenthesis at end of file")
    return lines


def _tokenize(line: str):
    tokens = []
    i, n = 0, len(line)
    while i < n:
        while i < n and line[i].isspace():
            i += 1
        if i >= n:
            break
        if line[i] == '"':
            j = i + 1
            chars = []
            while j < n and line[j] != '"':
                chars.append(line[j])
                j += 1
            if j >= n:
                raise ZoneFileError(f"unterminated quoted string: {line!r}")
            tokens.append(("qstring", "".join(chars)))
            i = j + 1
        else:
            j = i
            while j < n and not line[j].isspace():
                j += 1
            tokens.append(("word", line[i:j]))
            i = j
    return tokens


def _resolve_name(text: str, origin: Name) -> Name:
    if text == "@":
        return origin
    if text.endswith("."):
        return Name.from_text(text)
    return Name(Name.from_text(text).labels + origin.labels)


def _parse_ttl(text: str) -> int:
    text = text.strip()
    if text.isdigit():
        return int(text)
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    total, num = 0, ""
    for ch in text.lower():
        if ch.isdigit():
            num += ch
        elif ch in units:
            if not num:
                raise ZoneFileError(f"invalid TTL/time value: {text!r}")
            total += int(num) * units[ch]
            num = ""
        else:
            raise ZoneFileError(f"invalid TTL/time value: {text!r}")
    if num:
        raise ZoneFileError(f"invalid TTL/time value: {text!r} (trailing digits without a unit)")
    return total


def _build_rr(owner: Name, rtype_word: str, rclass: int, ttl: int, tokens, origin: Name) -> RR:
    rtype = NAME_TO_TYPE[rtype_word]
    vals = [v for _, v in tokens]
    if rtype == TYPE_A:
        if len(vals) != 1:
            raise ZoneFileError(f"A record for {owner} needs exactly 1 field, got {vals}")
        rd = rdata.A(vals[0])
    elif rtype == TYPE_AAAA:
        if len(vals) != 1:
            raise ZoneFileError(f"AAAA record for {owner} needs exactly 1 field, got {vals}")
        rd = rdata.AAAA(vals[0])
    elif rtype == TYPE_NS:
        rd = rdata.NS(_resolve_name(vals[0], origin))
    elif rtype == TYPE_CNAME:
        rd = rdata.CNAME(_resolve_name(vals[0], origin))
    elif rtype == TYPE_PTR:
        rd = rdata.PTR(_resolve_name(vals[0], origin))
    elif rtype == TYPE_MX:
        if len(vals) != 2:
            raise ZoneFileError(f"MX record for {owner} needs 'preference exchange', got {vals}")
        rd = rdata.MX(int(vals[0]), _resolve_name(vals[1], origin))
    elif rtype == TYPE_TXT:
        strings = tuple(v.encode("utf-8") for v in vals) if vals else (b"",)
        rd = rdata.TXT(strings)
    elif rtype == TYPE_SOA:
        if len(vals) != 7:
            raise ZoneFileError(
                f"SOA record for {owner} needs 7 fields "
                f"(mname rname serial refresh retry expire minimum), got {vals}"
            )
        mname = _resolve_name(vals[0], origin)
        rname = _resolve_name(vals[1], origin)
        serial = int(vals[2])
        refresh, retry, expire, minimum = (_parse_ttl(v) for v in vals[3:7])
        rd = rdata.SOA(mname, rname, serial, refresh, retry, expire, minimum)
    else:
        raise ZoneFileError(f"unsupported record type {rtype_word!r}")
    return RR(owner, rtype, rclass, ttl, rd)


def parse_zone(text: str, origin: Name, default_ttl: int | None = None):
    """Parse zone-file text into (list[RR], final_origin)."""
    current_origin = origin
    ttl_default = default_ttl
    last_owner = None
    last_used_ttl = None
    entries = []

    for logical, unindented in _logical_lines(text):
        tokens = _tokenize(logical)
        if not tokens:
            continue
        if tokens[0] == ("word", "$ORIGIN"):
            if len(tokens) < 2:
                raise ZoneFileError("$ORIGIN needs an argument")
            current_origin = _resolve_name(tokens[1][1], current_origin)
            continue
        if tokens[0] == ("word", "$TTL"):
            if len(tokens) < 2:
                raise ZoneFileError("$TTL needs an argument")
            ttl_default = _parse_ttl(tokens[1][1])
            continue

        idx = 0
        if unindented:
            if tokens[0][0] != "word":
                raise ZoneFileError(f"owner name cannot be a quoted string: {logical!r}")
            owner_text = tokens[0][1]
            idx = 1
        else:
            owner_text = None

        if owner_text is None:
            if last_owner is None:
                raise ZoneFileError(f"record has no owner and none inherited yet: {logical!r}")
            owner = last_owner
        else:
            owner = _resolve_name(owner_text, current_origin)

        ttl = None
        rclass = CLASS_IN
        rtype_word = None
        while idx < len(tokens):
            kind, val = tokens[idx]
            if kind != "word":
                raise ZoneFileError(f"unexpected quoted string in record header: {val!r}")
            upper = val.upper()
            if upper in RRTYPE_WORDS:
                rtype_word = upper
                idx += 1
                break
            if upper in CLASS_WORDS:
                idx += 1
                continue
            if val.isdigit():
                ttl = int(val)
                idx += 1
                continue
            raise ZoneFileError(f"unrecognized token {val!r} in record header: {logical!r}")

        if rtype_word is None:
            raise ZoneFileError(f"record is missing a type: {logical!r}")
        if ttl is None:
            ttl = last_used_ttl if last_used_ttl is not None else ttl_default
        if ttl is None:
            raise ZoneFileError(f"record for {owner} has no TTL and no $TTL default is set")
        last_used_ttl = ttl

        rr = _build_rr(owner, rtype_word, rclass, ttl, tokens[idx:], current_origin)
        entries.append(rr)
        last_owner = owner

    return entries, current_origin


@dataclass
class Zone:
    origin: Name
    records: dict = field(default_factory=dict)  # Name -> list[RR]
    soa: object = None  # rdata.SOA of the apex

    @staticmethod
    def from_text(text: str, origin: Name, default_ttl: int | None = None) -> "Zone":
        entries, final_origin = parse_zone(text, origin, default_ttl)
        zone = Zone(origin=final_origin)
        for rr in entries:
            if not rr.name.is_subdomain_of(zone.origin):
                raise ZoneFileError(
                    f"record owner {rr.name} is outside zone origin {zone.origin}"
                )
            zone.records.setdefault(rr.name, []).append(rr)
        apex_soa = [rr for rr in zone.records.get(zone.origin, []) if rr.rtype == TYPE_SOA]
        if len(apex_soa) != 1:
            raise ZoneFileError(
                f"zone {zone.origin} must have exactly one apex SOA record, found {len(apex_soa)}"
            )
        zone.soa = apex_soa[0].rdata
        return zone

    @staticmethod
    def from_file(path: str, origin: Name, default_ttl: int | None = None) -> "Zone":
        with open(path, "r", encoding="ascii") as f:
            text = f.read()
        return Zone.from_text(text, origin, default_ttl)

    def find_zone_cut(self, qname: Name):
        """Walk from qname up to (but excluding) the apex looking for a
        delegation (an owner name with NS records that isn't the zone's own
        apex). Returns (owner_name, list[RR]) or None."""
        if not qname.is_subdomain_of(self.origin):
            return None
        name = qname
        while True:
            if name != self.origin:
                recs = self.records.get(name, [])
                ns_recs = [r for r in recs if r.rtype == TYPE_NS]
                if ns_recs:
                    return name, ns_recs
            if name == self.origin:
                return None
            name = name.parent()

    def glue_for(self, ns_records) -> list:
        """A/AAAA records for each NS target that this zone happens to hold
        (i.e. in-bailiwick glue) -- exactly what a real parent zone ships in
        the additional section of a referral."""
        glue = []
        for ns in ns_records:
            for rr in self.records.get(ns.rdata.nsdname, []):
                if rr.rtype in (TYPE_A, TYPE_AAAA):
                    glue.append(rr)
        return glue

    def is_empty_non_terminal(self, qname: Name) -> bool:
        """True if qname itself has no node, but some name *below* it does
        (e.g. only 'c.b.a.example.com' exists, so 'b.a.example.com' is a
        real, NODATA node in the tree, not NXDOMAIN)."""
        return any(other != qname and other.is_subdomain_of(qname) for other in self.records)

    def wildcard_match(self, qname: Name):
        """Single-label wildcard lookup: '*.<parent>' matches a direct child
        of <parent> when no more specific node exists. (Real DNS wildcard
        matching per RFC 1034 4.3.2 is closest-encloser based and can match
        arbitrarily deep names; this simplified version -- covering the
        overwhelmingly common single-level case -- is a documented, known
        scope limit, not a bug: see REVIEW.md.)"""
        if len(qname.labels) <= len(self.origin.labels):
            return None
        candidate = Name((b"*",) + qname.labels[1:])
        return self.records.get(candidate)
