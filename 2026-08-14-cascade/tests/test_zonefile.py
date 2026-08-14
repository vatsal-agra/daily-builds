import pytest

from cascade.consts import TYPE_A, TYPE_SOA, TYPE_TXT
from cascade.name import Name
from cascade.zonefile import Zone, ZoneFileError, parse_zone


def test_basic_parse():
    text = """
$TTL 3600
$ORIGIN example.com.
@   IN SOA ns1.example.com. hostmaster.example.com. (1 2 3 4 5)
@   IN NS  ns1.example.com.
ns1 IN A   1.2.3.4
www IN A   1.2.3.5
"""
    zone = Zone.from_text(text, Name.from_text("example.com."))
    assert zone.origin == Name.from_text("example.com.")
    assert zone.soa.serial == 1
    a = zone.records[Name.from_text("www.example.com.")]
    assert a[0].rdata.address == "1.2.3.5"


def test_owner_name_inherited_when_indented():
    text = """
$TTL 3600
$ORIGIN example.com.
@   IN SOA ns1.example.com. hostmaster.example.com. (1 2 3 4 5)
@   IN NS  ns1.example.com.
ns1.example.com. IN A 1.2.3.4
    IN TXT "second record, same owner as the line above"
"""
    zone = Zone.from_text(text, Name.from_text("example.com."))
    recs = zone.records[Name.from_text("ns1.example.com.")]
    types = {r.rtype for r in recs}
    assert TYPE_A in types and TYPE_TXT in types


def test_ttl_inheritance_from_dollar_ttl_and_previous_record():
    text = """
$TTL 300
$ORIGIN example.com.
@   IN SOA ns1.example.com. hostmaster.example.com. (1 2 3 4 5)
@   IN NS  ns1.example.com.
a   600 IN A 1.1.1.1
b       IN A 1.1.1.2
"""
    zone = Zone.from_text(text, Name.from_text("example.com."))
    a = zone.records[Name.from_text("a.example.com.")][0]
    b = zone.records[Name.from_text("b.example.com.")][0]
    assert a.ttl == 600
    assert b.ttl == 600  # inherits the previous record's TTL, not back to $TTL 300


def test_ttl_with_unit_suffixes():
    text = """
$TTL 1h
$ORIGIN example.com.
@ IN SOA ns1.example.com. hostmaster.example.com. (1 1h 15m 1w 1d)
@ IN NS ns1.example.com.
"""
    zone = Zone.from_text(text, Name.from_text("example.com."))
    assert zone.soa.refresh == 3600
    assert zone.soa.retry == 900
    assert zone.soa.expire == 604800
    assert zone.soa.minimum == 86400
    apex = zone.records[zone.origin]
    ns = [r for r in apex if r.rtype != TYPE_SOA][0]
    assert ns.ttl == 3600


def test_at_sign_and_relative_names_resolve_against_origin():
    text = """
$ORIGIN example.com.
@    3600 IN SOA ns1.example.com. hostmaster.example.com. (1 2 3 4 5)
@    3600 IN NS  ns1
www  3600 IN CNAME @
"""
    zone = Zone.from_text(text, Name.from_text("example.com."))
    ns = [r for r in zone.records[zone.origin] if r.rtype != TYPE_SOA][0]
    assert ns.rdata.nsdname.to_text() == "ns1.example.com."
    cname = zone.records[Name.from_text("www.example.com.")][0]
    assert cname.rdata.cname == zone.origin


def test_origin_directive_can_change_mid_file():
    text = """
$TTL 3600
$ORIGIN example.com.
@ IN SOA ns1.example.com. hostmaster.example.com. (1 2 3 4 5)
@ IN NS ns1.example.com.
$ORIGIN sub.example.com.
host IN A 9.9.9.9
"""
    zone = Zone.from_text(text, Name.from_text("example.com."))
    assert zone.records[Name.from_text("host.sub.example.com.")][0].rdata.address == "9.9.9.9"


def test_parens_inside_quoted_txt_are_preserved():
    # Regression test for REVIEW.md #3: parens inside a TXT string used to
    # be silently deleted by the (non-quote-aware) line-joining logic.
    text = """
$TTL 3600
$ORIGIN example.com.
@    IN SOA ns1.example.com. hostmaster.example.com. (1 2 3 4 5)
@    IN NS  ns1.example.com.
note IN TXT "call us at (555) 123-4567"
"""
    zone = Zone.from_text(text, Name.from_text("example.com."))
    txt = zone.records[Name.from_text("note.example.com.")][0]
    assert txt.rdata.strings == (b"call us at (555) 123-4567",)


def test_parens_still_join_multiline_records_correctly():
    text = """
$ORIGIN example.com.
@ 3600 IN SOA ns1.example.com. hostmaster.example.com. (
    2026081401
    3600
    900
    604800
    3600
)
@ 3600 IN NS ns1.example.com.
"""
    zone = Zone.from_text(text, Name.from_text("example.com."))
    assert zone.soa.serial == 2026081401 and zone.soa.minimum == 3600


def test_comment_stripping_is_quote_aware():
    text = """
$TTL 3600
$ORIGIN example.com.
@    IN SOA ns1.example.com. hostmaster.example.com. (1 2 3 4 5)
@    IN NS  ns1.example.com.
note IN TXT "this has a semicolon ; right here" ; but this part is a real comment
"""
    zone = Zone.from_text(text, Name.from_text("example.com."))
    txt = zone.records[Name.from_text("note.example.com.")][0]
    assert txt.rdata.strings == (b"this has a semicolon ; right here",)


def test_missing_apex_soa_rejected():
    text = """
$ORIGIN example.com.
@ 3600 IN NS ns1.example.com.
"""
    with pytest.raises(ZoneFileError):
        Zone.from_text(text, Name.from_text("example.com."))


def test_record_outside_origin_rejected():
    text = """
$ORIGIN example.com.
@ 3600 IN SOA ns1.example.com. hostmaster.example.com. (1 2 3 4 5)
@ 3600 IN NS ns1.example.com.
evil.other-domain.org. 3600 IN A 6.6.6.6
"""
    with pytest.raises(ZoneFileError):
        Zone.from_text(text, Name.from_text("example.com."))


def test_no_ttl_and_no_dollar_ttl_rejected():
    text = """
$ORIGIN example.com.
@ IN SOA ns1.example.com. hostmaster.example.com. (1 2 3 4 5)
"""
    with pytest.raises(ZoneFileError):
        Zone.from_text(text, Name.from_text("example.com."))


def test_unbalanced_parens_rejected():
    text = """
$ORIGIN example.com.
@ 3600 IN SOA ns1.example.com. hostmaster.example.com. (1 2 3 4 5
"""
    with pytest.raises(ZoneFileError):
        Zone.from_text(text, Name.from_text("example.com."))


def test_find_zone_cut_and_glue():
    text = """
$TTL 3600
$ORIGIN example.com.
@                IN SOA ns1.example.com. hostmaster.example.com. (1 2 3 4 5)
@                IN NS  ns1.example.com.
ns1.example.com. IN A   1.2.3.4
dev.example.com. IN NS  ns1.dev.example.com.
ns1.dev.example.com. IN A 1.2.3.5
"""
    zone = Zone.from_text(text, Name.from_text("example.com."))
    cut = zone.find_zone_cut(Name.from_text("foo.dev.example.com."))
    assert cut is not None
    cut_name, ns_recs = cut
    assert cut_name == Name.from_text("dev.example.com.")
    glue = zone.glue_for(ns_recs)
    assert any(rr.rdata.address == "1.2.3.5" for rr in glue)
    # the zone's own apex is not itself a delegation
    assert zone.find_zone_cut(zone.origin) is None


def test_is_empty_non_terminal_and_wildcard():
    text = """
$TTL 3600
$ORIGIN example.com.
@   IN SOA ns1.example.com. hostmaster.example.com. (1 2 3 4 5)
@   IN NS  ns1.example.com.
ns1 IN A 1.2.3.4
*   IN A 9.9.9.9
a.b IN A 8.8.8.8
"""
    zone = Zone.from_text(text, Name.from_text("example.com."))
    assert zone.is_empty_non_terminal(Name.from_text("b.example.com."))
    assert not zone.is_empty_non_terminal(Name.from_text("a.b.example.com."))
    match = zone.wildcard_match(Name.from_text("anything.example.com."))
    assert match and match[0].rdata.address == "9.9.9.9"
    assert zone.wildcard_match(zone.origin) is None  # can't wildcard-match the apex itself
