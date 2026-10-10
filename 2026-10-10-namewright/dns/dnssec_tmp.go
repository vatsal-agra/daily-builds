package dns

// Temporary scaffolding replaced by dnssec.go in phase 4.
func (r *Resolver) validateAnswer(m *Message, chain, sigs []RR, name string, depth int) (SecStatus, string) {
	return Indeterminate, ""
}
func (r *Resolver) validateNegative(m *Message, name string, t Type, depth int) (SecStatus, string) {
	return Indeterminate, ""
}
func (r *Resolver) checkReferral(m *Message, zone string, cur *delegation, depth int) string {
	return ""
}
