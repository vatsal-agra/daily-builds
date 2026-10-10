# Adversarial review

Method: I re-read every file as a hostile reviewer, wrote down every suspicion, and turned each into
a failing test **before** touching the code (`dns/review_test.go`). I also ran 40 s of native Go
fuzzing on the wire decoder (re-encode/decode invariants, ~1.5 M execs) and 25 s on the zone parser,
exercised the CLI with bad input, ran the suite under `-race`, and diffed my zone parser against
dnspython's on all five sample zones. Results below; "Test" names the regression test that failed
against the phase-2 code and passes now.

## Defects found and fixed (first pass: R1–R14)

| ID | Sev | Finding | Evidence | Fix | Test |
|----|-----|---------|----------|-----|------|
| R1 | **High** | Loop detection set (`inflight`) lived on the `Resolver`, shared by all goroutines. Two clients asking for the same name at once made each other fail with "dependency loop" → SERVFAIL. A recursive server would fail under any real load. | 39 of 40 concurrent lookups SERVFAILed | Loop set is per-resolution (`resState`) | `TestReviewConcurrentIdenticalResolves` |
| R2 | **High** | Server selection skipped "recently failed" servers outright; with ≥2 servers all marked bad, *none* was tried, so a zone stayed unreachable for 10 s after the servers recovered. | Root restarted, resolver still SERVFAIL | Failed servers sort last but are never skipped | `TestReviewAllServersMarkedBadStillTried` |
| R3 | **High** | Found only by `-race` runs: the NS set was cached a moment before its glue. A concurrent lookup saw NS without addresses, tried to resolve a nameserver *by asking that nameserver*, and failed. The same wedge happens whenever glue expires or is evicted before its NS set. | `no addresses for the nameservers of example.com.` | `bestDelegation` skips a level whose in-bailiwick servers have no address, so the parent's referral re-supplies glue | `TestReviewLostGlueFallsBackToParent` |
| R4 | Med | 0x20 case randomisation was mandatory. Servers that lower-case the question (some do) failed the check and were declared dead. | SERVFAIL against a case-folding server | Distinct `ErrCase0x20`; resolver retries once without randomisation | `TestReviewCase0x20Fallback` |
| R5 | Med | Cache ignored RFC 2181 §5.4.1 trust ranking: parent glue overwrote data learned from an authoritative answer. | `ns.example. A` replaced by glue value | `PutSetTrust` with `TrustGlue < TrustAnswer`; unexpired higher-rank data is never displaced | `TestReviewCacheTrustRanking` |
| R6 | Med | Unlimited concurrent TCP connections (slow-loris style exhaustion). | — | `MaxTCPConns` (default 1024), excess closed immediately, `tcp-rejected` stat | `TestReviewTCPConnectionCap` |
| R7 | Med | AXFR client trusted the primary: an endless stream filled memory. | transfer of 2000 records accepted with a 100 cap | `MaxTransferRecords` (default 1 M) | `TestReviewAXFRRecordCap` |
| R8 | Med | A DS query at a zone cut was answered by the *child* zone when parent and child live on the same server (wrong SOA, breaks DNSSEC chain walking). | authority SOA was `c.p.` | DS for a zone apex is answered from the parent zone | `TestReviewDSAnsweredByParentWhenCoHosted` |
| R9 | Low | `NSEC` type list kept in file order in presentation, so equal records printed differently. | `b. TXT A RRSIG NS` | sorted at parse | `TestReviewNSECTypesSorted` |
| R10 | Low | UTF-8 BOM at file start broke the first directive. | `relative name "﻿$ORIGIN"` | BOM stripped | `TestReviewBOM` |
| R11 | Low | Rate limiter keyed `::ffff:1.2.3.4` and `1.2.3.4` separately → limit bypass on dual-stack sockets. | fresh bucket for mapped form | address unmapped before keying | `TestReviewRateLimiterUnmaps` |
| R12 | Med | `Server.Close()` blocked up to 10 s on any idle TCP client. | Close took > 2 s | open connections tracked and closed on shutdown | `TestReviewCloseDoesNotWaitForIdleTCP` |
| R13 | Med | Names containing `\DDD` escapes were not canonicalised: zone file `\097bc` never matched wire name `abc`. | NXDOMAIN for an existing name | `CanonName` normalises through label parsing | `TestReviewEscapedNameEquivalence` |
| R14 | Med | Thundering herd: 40 identical concurrent client queries produced 40 full root-to-leaf walks. | root saw ~40 queries | in-flight coalescing (singleflight) per `(name,type)`, panic-safe | `TestReviewSingleflight` |

## UX defects found and fixed

* `dig A example.com` (type first) was rejected; now accepted.
* `resolve` printed "1 upstream queries"; fixed pluralisation and says "all from cache" when true.
* `dig` against a closed port printed a raw `read udp ...: connection refused`; now a one-line explanation.
* The mini-internet zone files were found via a CWD-relative path (`testdata/internet`) so `namewright resolve`
  only worked from the project root. They are now `go:embed`-ed (override with `-world dir`).

## Suspected but refuted

* **Deep empty non-terminals** (e.g. `w.x.y.k` when only `y.k` exists): I suspected the ENT scan stopped at the first
  existing ancestor and missed higher ENTs. Tests show every node's own ancestor walk covers its chain, so there is
  no bug; the test stays as a regression guard (`TestReviewDeepEmptyNonTerminal`).
* **Fuzzing** found no panic or round-trip violation in the wire decoder or the zone parser.
* **Zone parser vs dnspython**: identical presentation output for all five sample zones.

## Known limitations (deliberate, documented, not bugs)

DNAME, IXFR, NOTIFY/UPDATE, EDNS cookies, qname minimisation (RFC 9156) and classes other than IN are not
implemented. Zone `$INCLUDE`/`$GENERATE` are rejected with a clear error rather than ignored.

## Fresh run-through

After the fixes: full suite under `-race` ×3 green, CLI battery (11 bad-input invocations) gives one-line
errors with correct exit codes, fuzzers re-run clean, and none of R1–R14 reproduce.

---

# Second pass: re-reviewing the Phase 4 code (DNSSEC, secondary, policy)

Same method: suspicion → failing test → fix. These were found *after* the stretch features landed.

| ID | Sev | Finding | Fix | Test |
|----|-----|---------|-----|------|
| R15 | **High** | Validated answers were cached for their record TTL even when the covering RRSIG expires sooner, so a resolver would keep serving "secure" data after its signatures lapsed (RFC 4035 §5.3.3). Same for cached DNSKEY sets. | TTLs clamped to the remaining signature lifetime, both for what is cached and what is returned; key-cache lifetime capped likewise | `TestSecureCacheEntriesDieWithTheirSignatures` |
| R16 | Med | Zone loading "harmonised" TTLs across the whole RRSIG RRset at a name, so every signature at a node took the smallest covered TTL (visible: `web.example.com. 300 IN RRSIG A … 600`). | RRSIGs excluded from harmonisation; each keeps its covered RRset's TTL | `TestReviewRRSIGTTLMatchesCoveredRRset` |
| R17 | **High** | (caught by the first validating run) the CNAME-follow step took the *last* record of a step result as the CNAME; with RRSIGs appended that is an RRSIG → type-assertion **panic** in the resolver. | CNAME located by type, not position | every DNSSEC resolver test |

Design checks that held up (CD results never write to the cache; unvalidated entries are misses for validating lookups — covered by `expectBogus`). Also verified in this pass: wildcard-NODATA validation (`TestWildcardNODATAValidates`), rate-limiter and
policy behaviour (`TestRateLimitingOnServer`, `TestResponsePolicy`), secondary expiry/serial-regression
handling (`TestSecondaryFollowsPrimary`), and the whole DNSSEC implementation against dnspython
(`tests/crosscheck.py`: dnspython validates our RRSIGs for Ed25519 + ECDSA, wildcard expansion, NSEC and DS digests;
and `namewright verify` accepts zones signed by dnspython — which would be impossible if the canonical-form code differed).

Known DNSSEC limitations (documented, fail-closed where it matters): NSEC3 is not supported (a secure zone answering
with NSEC3 yields BOGUS with an explicit reason), no RFC 5011 key rollover tracking, RSA verifies but cannot sign,
no signature-inception clock-skew tolerance.
