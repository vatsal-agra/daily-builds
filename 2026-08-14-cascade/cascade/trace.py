"""Records what actually happened during a resolution, so the CLI's
`--trace` output and the HTML visualizer are built from a real recorded
run, not a canned diagram."""

from __future__ import annotations

from dataclasses import dataclass, field

from .textfmt import fmt_rr, rcode_name, type_name


@dataclass
class TraceStep:
    kind: str                    # 'query' | 'cache_hit' | 'referral' | 'answer' | 'nxdomain' | 'error'
    qname: str
    qtype: str
    detail: str
    server_name: str | None = None
    server_addr: str | None = None
    rcode: str | None = None
    answer_lines: list = field(default_factory=list)
    authority_lines: list = field(default_factory=list)
    additional_lines: list = field(default_factory=list)


class Trace:
    def __init__(self):
        self.steps: list[TraceStep] = []

    def query(self, qname, qtype, server_name, server_addr, resp) -> TraceStep:
        step = TraceStep(
            kind="query",
            qname=qname.to_text(), qtype=type_name(qtype),
            server_name=server_name.to_text() if server_name is not None else None,
            server_addr=server_addr,
            rcode=rcode_name(resp.rcode),
            answer_lines=[fmt_rr(r) for r in resp.answers],
            authority_lines=[fmt_rr(r) for r in resp.authority],
            additional_lines=[fmt_rr(r) for r in resp.additional],
            detail=(
                "authoritative answer" if resp.aa and resp.answers else
                "NXDOMAIN" if resp.rcode == 3 else
                "NODATA" if resp.aa else
                "referral" if resp.authority else
                "empty response"
            ),
        )
        self.steps.append(step)
        return step

    def cache_hit(self, qname, qtype, detail) -> TraceStep:
        step = TraceStep(kind="cache_hit", qname=qname.to_text(), qtype=type_name(qtype), detail=detail)
        self.steps.append(step)
        return step

    def error(self, qname, qtype, detail) -> TraceStep:
        step = TraceStep(kind="error", qname=qname.to_text(), qtype=type_name(qtype), detail=detail)
        self.steps.append(step)
        return step
