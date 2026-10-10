package dns

// SecStatus is the DNSSEC validation outcome for a response (RFC 4035 §4.3).
type SecStatus int

const (
	Indeterminate SecStatus = iota // not validated
	Insecure                       // provably unsigned (no DS at a delegation)
	Secure                         // validated up to a trust anchor
	Bogus                          // signatures present but wrong/expired/missing
)

func (s SecStatus) String() string {
	return [...]string{"indeterminate", "insecure", "secure", "bogus"}[s]
}
