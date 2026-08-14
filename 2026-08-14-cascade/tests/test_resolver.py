import time

import pytest

from cascade.cache import Cache
from cascade.consts import TYPE_A, TYPE_AAAA, TYPE_MX, RCODE_NXDOMAIN
from cascade.name import Name
from cascade.resolver import Resolver, ResolutionError
from cascade.trace import Trace


def _resolver(fakenet, trace=None):
    return Resolver(fakenet.root_hints(), port=fakenet.port, cache=Cache(), trace=trace)


def test_full_recursive_resolution_walks_root_tld_authoritative(fakenet):
    trace = Trace()
    r = _resolver(fakenet, trace)
    result = r.resolve(Name.from_text("www.example.com."), TYPE_A)
    assert result.success
    assert any(rr.rdata.address == "93.184.216.34" for rr in result.answers if rr.rtype == TYPE_A)
    hops = [s for s in trace.steps if s.kind == "query"]
    assert len(hops) == 3
    assert hops[0].server_addr.startswith("127.0.0.2")   # root
    assert hops[1].server_addr.startswith("127.0.0.3")   # .com TLD
    assert hops[2].server_addr.startswith("127.0.0.4")   # example.com authoritative


def test_second_level_delegation_with_its_own_glue(fakenet):
    r = _resolver(fakenet)
    result = r.resolve(Name.from_text("api.dev.example.com."), TYPE_A)
    assert result.success
    assert result.answers[0].rdata.address == "127.0.0.6"


def test_wildcard_via_recursive_resolution(fakenet):
    r = _resolver(fakenet)
    result = r.resolve(Name.from_text("anything-goes.dev.example.com."), TYPE_A)
    assert result.success
    assert result.answers[0].rdata.address == "127.0.0.9"


def test_nxdomain_surfaces_cleanly(fakenet):
    r = _resolver(fakenet)
    result = r.resolve(Name.from_text("nope.example.com."), TYPE_A)
    assert result.rcode == RCODE_NXDOMAIN
    assert not result.answers


def test_aaaa_and_mx(fakenet):
    r = _resolver(fakenet)
    aaaa = r.resolve(Name.from_text("example.com."), TYPE_AAAA)
    assert aaaa.answers[0].rdata.address == "2606:2800:220:1:248:1893:25c8:1946"
    mx = r.resolve(Name.from_text("example.com."), TYPE_MX)
    assert mx.answers[0].rdata.preference == 10


def test_repeat_query_is_a_pure_cache_hit(fakenet):
    r = _resolver(fakenet)
    r.resolve(Name.from_text("www.example.com."), TYPE_A)
    before = r.queries_sent
    r.resolve(Name.from_text("www.example.com."), TYPE_A)
    assert r.queries_sent == before


def test_cached_cname_lets_chain_continue_from_cache(fakenet):
    # Regression check for the CNAME-cache-miss bug found during initial
    # smoke testing: a query that returns [CNAME, A] together caches both,
    # but a *later* query for a plain A record at the alias name must still
    # be a full cache hit by following the cached CNAME, not silently
    # re-querying the whole chain from the root.
    r = _resolver(fakenet)
    r.resolve(Name.from_text("www.example.com."), TYPE_A)
    before = r.queries_sent
    result = r.resolve(Name.from_text("www.example.com."), TYPE_A)
    assert r.queries_sent == before
    assert result.answers[-1].rdata.address == "93.184.216.34"


def test_repeat_nxdomain_is_negative_cached(fakenet):
    r = _resolver(fakenet)
    r.resolve(Name.from_text("nope.example.com."), TYPE_A)
    before = r.queries_sent
    r.resolve(Name.from_text("nope.example.com."), TYPE_A)
    assert r.queries_sent == before


def test_short_ttl_record_actually_expires_and_is_refetched(fakenet):
    r = _resolver(fakenet)
    first = r.resolve(Name.from_text("ticker.dev.example.com."), TYPE_A)
    assert first.answers[-1].ttl <= 2
    before = r.queries_sent
    time.sleep(2.3)
    r.resolve(Name.from_text("ticker.dev.example.com."), TYPE_A)
    assert r.queries_sent > before


def test_unreachable_root_raises_resolution_error():
    from cascade.resolver import RootHint
    bad_hint = RootHint(Name.from_text("nowhere."), "127.0.0.253")
    r = Resolver([bad_hint], port=59999, timeout=0.3)
    with pytest.raises(ResolutionError):
        r.resolve(Name.from_text("anything.com."), TYPE_A)
