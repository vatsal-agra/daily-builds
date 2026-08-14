from cascade.cache import Cache
from cascade.consts import TYPE_A, TYPE_AAAA, CLASS_IN
from cascade.message import RR
from cascade import rdata
from cascade.name import Name


def _soa_rr(ttl=300, minimum=60):
    return RR(Name.from_text("example.com."), 6, CLASS_IN, ttl,
              rdata.SOA(Name.from_text("ns1.example.com."), Name.from_text("host.example.com."),
                        1, 3600, 900, 604800, minimum))


def test_positive_cache_hit_and_ttl_countdown():
    cache = Cache()
    name = Name.from_text("www.example.com.")
    rr = RR(name, TYPE_A, CLASS_IN, 100, rdata.A("1.2.3.4"))
    cache.put_positive(name, TYPE_A, [rr], now=1000.0)
    got = cache.get_positive(name, TYPE_A, now=1010.0)
    assert got is not None
    assert got[0].ttl == 90  # 100 - 10 elapsed seconds
    assert cache.hits == 1


def test_positive_cache_expires():
    cache = Cache()
    name = Name.from_text("www.example.com.")
    rr = RR(name, TYPE_A, CLASS_IN, 10, rdata.A("1.2.3.4"))
    cache.put_positive(name, TYPE_A, [rr], now=1000.0)
    assert cache.get_positive(name, TYPE_A, now=1005.0) is not None
    assert cache.get_positive(name, TYPE_A, now=1011.0) is None  # 11s later, TTL was 10


def test_cache_is_per_type():
    cache = Cache()
    name = Name.from_text("dual.example.com.")
    cache.put_positive(name, TYPE_A, [RR(name, TYPE_A, CLASS_IN, 300, rdata.A("1.2.3.4"))])
    assert cache.get_positive(name, TYPE_AAAA) is None
    assert cache.get_positive(name, TYPE_A) is not None


def test_nxdomain_is_cached_per_name_across_all_types():
    cache = Cache()
    name = Name.from_text("nope.example.com.")
    cache.put_nxdomain(name, _soa_rr(ttl=300, minimum=60), now=1000.0)
    # RFC 2308: NXDOMAIN means the name doesn't exist at all, for any type
    assert cache.get_negative(name, TYPE_A, now=1010.0) == "nxdomain"
    assert cache.get_negative(name, TYPE_AAAA, now=1010.0) == "nxdomain"


def test_nxdomain_ttl_bounded_by_soa_minimum():
    cache = Cache()
    name = Name.from_text("nope.example.com.")
    # SOA record TTL is large, but SOA.minimum is small -- RFC 2308 says the
    # smaller of the two bounds the negative cache lifetime.
    cache.put_nxdomain(name, _soa_rr(ttl=10000, minimum=5), now=1000.0)
    assert cache.get_negative(name, TYPE_A, now=1004.0) == "nxdomain"
    assert cache.get_negative(name, TYPE_A, now=1006.0) is None


def test_nodata_is_cached_only_for_the_queried_type():
    cache = Cache()
    name = Name.from_text("example.com.")
    cache.put_nodata(name, TYPE_AAAA, _soa_rr(ttl=300, minimum=300), now=1000.0)
    assert cache.get_negative(name, TYPE_AAAA, now=1001.0) == "nodata"
    assert cache.get_negative(name, TYPE_A, now=1001.0) is None  # A wasn't NODATA, only AAAA was


def test_miss_counter():
    cache = Cache()
    name = Name.from_text("nowhere.example.com.")
    assert cache.get_positive(name, TYPE_A) is None
    assert cache.get_negative(name, TYPE_A) is None
    cache.record_miss()
    assert cache.misses == 1
    assert cache.hits == 0


def test_len_reflects_all_three_stores():
    cache = Cache()
    name = Name.from_text("a.example.com.")
    cache.put_positive(name, TYPE_A, [RR(name, TYPE_A, CLASS_IN, 300, rdata.A("1.1.1.1"))])
    cache.put_nxdomain(Name.from_text("b.example.com."), _soa_rr())
    cache.put_nodata(Name.from_text("c.example.com."), TYPE_AAAA, _soa_rr())
    assert len(cache) == 3
