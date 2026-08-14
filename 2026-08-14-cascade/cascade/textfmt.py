"""Human-readable rendering of names/rdata/messages -- shared by the CLI's
`dig` output and the trace recorder/visualizer, so both speak one format."""

from __future__ import annotations

from . import rdata as rd
from .consts import TYPE_NAMES, RCODE_NAMES


def type_name(rtype: int) -> str:
    return TYPE_NAMES.get(rtype, str(rtype))


def rcode_name(rcode: int) -> str:
    return RCODE_NAMES.get(rcode, str(rcode))


def fmt_rdata(rdata) -> str:
    if isinstance(rdata, rd.A):
        return rdata.address
    if isinstance(rdata, rd.AAAA):
        return rdata.address
    if isinstance(rdata, rd.NS):
        return rdata.nsdname.to_text()
    if isinstance(rdata, rd.CNAME):
        return rdata.cname.to_text()
    if isinstance(rdata, rd.PTR):
        return rdata.ptrdname.to_text()
    if isinstance(rdata, rd.MX):
        return f"{rdata.preference} {rdata.exchange.to_text()}"
    if isinstance(rdata, rd.TXT):
        return " ".join(f'"{s.decode("utf-8", "replace")}"' for s in rdata.strings)
    if isinstance(rdata, rd.SOA):
        return (f"{rdata.mname.to_text()} {rdata.rname.to_text()} {rdata.serial} "
                f"{rdata.refresh} {rdata.retry} {rdata.expire} {rdata.minimum}")
    if isinstance(rdata, rd.RAW):
        return rdata.data.hex()
    return repr(rdata)


def fmt_rr(rr) -> str:
    return f"{rr.name.to_text()} {rr.ttl} IN {type_name(rr.rtype)} {fmt_rdata(rr.rdata)}"


def fmt_message(msg, title: str | None = None) -> str:
    lines = []
    if title:
        lines.append(title)
    flags = []
    if msg.qr:
        flags.append("qr")
    if msg.aa:
        flags.append("aa")
    if msg.tc:
        flags.append("tc")
    if msg.rd:
        flags.append("rd")
    if msg.ra:
        flags.append("ra")
    lines.append(
        f";; ->>HEADER<<- opcode: {msg.opcode}, status: {rcode_name(msg.rcode)}, id: {msg.id}"
    )
    lines.append(f";; flags: {' '.join(flags)}; QUERY: {len(msg.questions)}, "
                 f"ANSWER: {len(msg.answers)}, AUTHORITY: {len(msg.authority)}, "
                 f"ADDITIONAL: {len(msg.additional)}")
    if msg.questions:
        lines.append("")
        lines.append(";; QUESTION SECTION:")
        for q in msg.questions:
            lines.append(f";{q.qname.to_text()} IN {type_name(q.qtype)}")
    for label, section in (("ANSWER", msg.answers), ("AUTHORITY", msg.authority),
                            ("ADDITIONAL", msg.additional)):
        if section:
            lines.append("")
            lines.append(f";; {label} SECTION:")
            for rr in section:
                lines.append(fmt_rr(rr))
    return "\n".join(lines)
