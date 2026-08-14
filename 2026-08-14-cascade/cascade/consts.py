"""DNS wire-format constants (RFC 1035, RFC 2308, RFC 6891)."""

# RR types we implement (there are dozens more in the real registry; these
# cover a normal zone plus EDNS0).
TYPE_A = 1
TYPE_NS = 2
TYPE_CNAME = 5
TYPE_SOA = 6
TYPE_PTR = 12
TYPE_MX = 15
TYPE_TXT = 16
TYPE_AAAA = 28
TYPE_OPT = 41  # EDNS0 pseudo-RR (RFC 6891)
TYPE_ANY = 255

TYPE_NAMES = {
    TYPE_A: "A", TYPE_NS: "NS", TYPE_CNAME: "CNAME", TYPE_SOA: "SOA",
    TYPE_PTR: "PTR", TYPE_MX: "MX", TYPE_TXT: "TXT", TYPE_AAAA: "AAAA",
    TYPE_OPT: "OPT", TYPE_ANY: "ANY",
}
NAME_TO_TYPE = {v: k for k, v in TYPE_NAMES.items()}

CLASS_IN = 1
CLASS_ANY = 255

OPCODE_QUERY = 0

RCODE_NOERROR = 0
RCODE_FORMERR = 1
RCODE_SERVFAIL = 2
RCODE_NXDOMAIN = 3
RCODE_NOTIMP = 4
RCODE_REFUSED = 5

RCODE_NAMES = {
    RCODE_NOERROR: "NOERROR", RCODE_FORMERR: "FORMERR",
    RCODE_SERVFAIL: "SERVFAIL", RCODE_NXDOMAIN: "NXDOMAIN",
    RCODE_NOTIMP: "NOTIMP", RCODE_REFUSED: "REFUSED",
}

# Real DNS wire packets are size-bounded: the classic pre-EDNS0 UDP limit,
# and the practical EDNS0-advertised limit this implementation uses.
CLASSIC_UDP_MAX = 512
EDNS_UDP_MAX = 4096
