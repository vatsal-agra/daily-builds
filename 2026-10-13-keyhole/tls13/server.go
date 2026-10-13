package tls13

import (
	"bytes"
	"crypto/x509"
	"errors"
	"io"
	"time"
)

const ticketLifetime = 24 * time.Hour

func containsU8(l []uint8, v uint8) bool {
	for _, x := range l {
		if x == v {
			return true
		}
	}
	return false
}

// pskCandidate is a ticket we could decrypt and that is currently valid.
type pskCandidate struct {
	idx   int
	state *sessionState
}

// findPSK looks for a decryptable, unexpired ticket among the client's identities.
func (c *Conn) findPSK(ch *clientHello) *pskCandidate {
	if len(ch.psks) == 0 || !containsU8(ch.pskModes, pskModeDHE) {
		return nil
	}
	key := c.cfg.sealKey()
	for i, id := range ch.psks {
		st, ok := openTicket(key, id.identity)
		if !ok {
			continue
		}
		age := c.cfg.now().Sub(st.created)
		if age < -time.Minute || age > ticketLifetime {
			continue
		}
		if st.serverName != "" && ch.serverName != "" && st.serverName != ch.serverName {
			continue
		}
		if suiteByID(st.suite) == nil {
			continue
		}
		return &pskCandidate{i, st}
	}
	return nil
}

// selectSuite picks by server preference among the client's offers; sameHashAs>0 restricts to suites
// with that digest length (needed to use a PSK), and prefer, if offered, wins within that restriction.
func (c *Conn) selectSuite(ch *clientHello, sameHashAs int, prefer uint16) *suite {
	var best *suite
	for _, s := range c.cfg.suites() {
		if !offersSuite(ch.suites, s.id) {
			continue
		}
		if sameHashAs > 0 && s.hashLen() != sameHashAs {
			continue
		}
		if s.id == prefer {
			return s
		}
		if best == nil {
			best = s
		}
	}
	return best
}

func (c *Conn) serverHandshake() error {
	cfg := c.cfg
	if len(cfg.Certificates) == 0 && cfg.GetCertificate == nil {
		return errors.New("tls13: server has no certificates configured")
	}
	msg, err := c.readHS(hsClientHello)
	if err != nil {
		return err
	}
	ch, err := parseClientHello(msg)
	if err != nil {
		return err
	}
	c.clientRandom = ch.random
	if !offersSuite(ch.versions, versionTLS13) {
		return fail(AlertProtocolVersion, "client does not offer TLS 1.3")
	}
	if len(ch.groups) == 0 || !ch.hasExt[extKeyShare] && !ch.hasExt[extSupportedGroups] {
		return fail(AlertMissingExtension, "ClientHello lacks supported_groups")
	}
	cand := c.findPSK(ch)
	if cand == nil && !ch.hasExt[extSignatureAlgorithms] {
		return fail(AlertMissingExtension, "ClientHello lacks signature_algorithms")
	}
	if ch.hasExt[extPreSharedKey] && !ch.hasExt[extPSKKeyExchangeModes] {
		return fail(AlertMissingExtension, "pre_shared_key without psk_key_exchange_modes")
	}

	// Cipher suite (a valid PSK constrains the digest).
	var st *suite
	if cand != nil {
		st = c.selectSuite(ch, suiteByID(cand.state.suite).hashLen(), cand.state.suite)
		if st == nil {
			cand = nil
		}
	}
	if st == nil {
		st = c.selectSuite(ch, 0, 0)
	}
	if st == nil {
		return fail(AlertHandshakeFailure, "no cipher suite in common")
	}
	c.suite = st

	// Key exchange group.
	group, share, needHRR := uint16(0), []byte(nil), true
	for _, g := range cfg.groups() {
		if !offersSuite(ch.groups, g) {
			continue
		}
		for _, ks := range ch.keyShares {
			if ks.group == g {
				group, share, needHRR = g, ks.data, false
				break
			}
		}
		if !needHRR {
			break
		}
	}
	if needHRR {
		for _, g := range cfg.groups() {
			if offersSuite(ch.groups, g) {
				group = g
				break
			}
		}
		if group == 0 {
			return fail(AlertHandshakeFailure, "no key exchange group in common")
		}
	}
	for _, ks := range ch.keyShares { // every offered share must at least be well-formed for a group we know
		if curveFor(ks.group) != nil && !validPeerShare(ks.group, ks.data) && ks.group == group {
			return fail(AlertIllegalParameter, "invalid key share for %s", GroupName(ks.group))
		}
	}

	if needHRR {
		c.state.HelloRetryRequest = true
		hrr := &serverHello{random: helloRetryRequestRandom, sessionID: ch.sessionID, suite: st.id,
			hrr: true, hasKeyShr: true, keyShare: keyShareEntry{group: group}, pskSelect: -1}
		hrr.marshal()
		ch1 := c.transcript
		c.transcript = hsFrame(hsMessageHash, st.sum(ch1))
		if err := c.sendHS(hrr.raw); err != nil {
			return err
		}
		if len(ch.sessionID) > 0 {
			c.sendCCS()
		}
		if err := c.flushLocked(); err != nil {
			return err
		}
		msg, err = c.readHS(hsClientHello)
		if err != nil {
			return err
		}
		ch2, err := parseClientHello(msg)
		if err != nil {
			return err
		}
		if err := checkSecondHello(ch, ch2, group); err != nil {
			return err
		}
		ch = ch2
		share = ch.keyShares[0].data
		cand = c.findPSK(ch)
		if cand != nil && suiteByID(cand.state.suite).hashLen() != st.hashLen() {
			cand = nil
		}
	}

	// PSK binder.
	var psk []byte
	pskIdx := -1
	if cand != nil {
		ps := suiteByID(cand.state.suite)
		early := ps.earlySecret(cand.state.psk)
		bk := deriveSecret(ps.hash, early, "res binder", ps.sum(nil))
		partial := append(append([]byte(nil), c.transcript[:c.prevLen]...), ch.raw[:ch.bindersStart]...)
		want := ps.finishedMAC(bk, ps.sum(partial))
		if !ctEqual(want, ch.binders[cand.idx]) {
			return fail(AlertDecryptError, "PSK binder does not verify")
		}
		psk, pskIdx = cand.state.psk, cand.idx
		c.state.DidResume = true
	}

	// ALPN / SNI.
	alpn := ""
	if len(cfg.NextProtos) > 0 && len(ch.alpn) > 0 {
		for _, p := range cfg.NextProtos {
			if contains(ch.alpn, p) {
				alpn = p
				break
			}
		}
		if alpn == "" {
			return fail(AlertNoApplicationProtocol, "no application protocol in common")
		}
	}
	c.state.ServerName = ch.serverName
	c.state.NegotiatedProtocol = alpn
	c.state.CipherSuite = st.id
	c.state.Version = versionTLS13
	c.state.KeyShareGroup = group

	// Certificate selection (not needed on resumption).
	var cert *Certificate
	var sigAlg uint16
	if psk == nil {
		if cert, sigAlg, err = c.pickCertificate(ch); err != nil {
			return err
		}
	}

	kx, err := newKeyExchange(cfg.rand(), group)
	if err != nil {
		return err
	}
	ecdhe, err := kx.shared(share)
	if err != nil {
		return err
	}
	random, err := c.newRandom()
	if err != nil {
		return err
	}
	sh := &serverHello{random: random, sessionID: ch.sessionID, suite: st.id, hasKeyShr: true,
		keyShare: keyShareEntry{group, kx.public()}, pskSelect: pskIdx}
	sh.marshal()
	if err := c.sendHS(sh.raw); err != nil {
		return err
	}
	if len(ch.sessionID) > 0 && !c.state.HelloRetryRequest {
		c.sendCCS()
	}

	early := st.earlySecret(psk)
	hsSecret := st.handshakeSecret(early, ecdhe)
	th := c.transcriptHash()
	cHS := deriveSecret(st.hash, hsSecret, "c hs traffic", th)
	sHS := deriveSecret(st.hash, hsSecret, "s hs traffic", th)
	c.keyLog("CLIENT_HANDSHAKE_TRAFFIC_SECRET", cHS)
	c.keyLog("SERVER_HANDSHAKE_TRAFFIC_SECRET", sHS)
	if err := c.setWriteSecret(sHS, "server handshake traffic"); err != nil {
		return err
	}
	if err := c.setReadSecret(cHS, "client handshake traffic"); err != nil {
		return err
	}
	masterSecret := st.masterSecret(hsSecret)

	ee := &encryptedExtensions{alpn: alpn, hasALPN: alpn != "", serverName: cfg.GetCertificate != nil && ch.serverName != ""}
	if err := c.sendHS(ee.marshal()); err != nil {
		return err
	}
	askClient := psk == nil && cfg.ClientAuth != NoClientCert
	if askClient {
		if err := c.sendHS((&certificateRequest{sigAlgs: supportedSigAlgs}).marshal()); err != nil {
			return err
		}
	}
	if psk == nil {
		if err := c.sendHS((&certificateMsg{certs: cert.Chain}).marshal()); err != nil {
			return err
		}
		sig, err := signCertVerify(cfg.rand(), cert.Key, sigAlg, signedContent(true, c.transcriptHash()))
		if err != nil {
			return fail(AlertInternalError, "signing CertificateVerify: %v", err)
		}
		c.state.SignatureAlgorithm = sigAlg
		if err := c.sendHS((&certificateVerify{alg: sigAlg, sig: sig}).marshal()); err != nil {
			return err
		}
	}
	if err := c.sendHS(hsFrame(hsFinished, st.finishedMAC(sHS, c.transcriptHash()))); err != nil {
		return err
	}
	th = c.transcriptHash() // CH..server Finished
	cAP := deriveSecret(st.hash, masterSecret, "c ap traffic", th)
	sAP := deriveSecret(st.hash, masterSecret, "s ap traffic", th)
	c.exporterMaster = deriveSecret(st.hash, masterSecret, "exp master", th)
	c.keyLog("CLIENT_TRAFFIC_SECRET_0", cAP)
	c.keyLog("SERVER_TRAFFIC_SECRET_0", sAP)
	c.keyLog("EXPORTER_SECRET", c.exporterMaster)
	if err := c.setWriteSecret(sAP, "server application traffic"); err != nil {
		return err
	}
	if err := c.flushLocked(); err != nil {
		return err
	}

	// ---- client flight ----
	if askClient {
		if err := c.readClientAuth(); err != nil {
			return err
		}
	}
	msg, err = c.readHS(hsFinished)
	if err != nil {
		return err
	}
	if want := st.finishedMAC(cHS, c.transcriptHashBefore()); len(msg)-4 != len(want) || !ctEqual(msg[4:], want) {
		return fail(AlertDecryptError, "client Finished verify_data is wrong")
	}
	if err := c.setReadSecret(cAP, "client application traffic"); err != nil {
		return err
	}
	c.resMaster = deriveSecret(st.hash, masterSecret, "res master", c.transcriptHash())
	if !cfg.NoTickets {
		return c.sendTicket()
	}
	return nil
}

// checkSecondHello enforces RFC 8446 §4.1.2: CH2 may differ from CH1 only in the permitted fields.
func checkSecondHello(a, b *clientHello, group uint16) error {
	if !bytes.Equal(a.random, b.random) || !bytes.Equal(a.sessionID, b.sessionID) {
		return fail(AlertIllegalParameter, "second ClientHello changed random or session id")
	}
	if len(a.suites) != len(b.suites) {
		return fail(AlertIllegalParameter, "second ClientHello changed the cipher suites")
	}
	for i := range a.suites {
		if a.suites[i] != b.suites[i] {
			return fail(AlertIllegalParameter, "second ClientHello changed the cipher suites")
		}
	}
	if len(b.keyShares) != 1 || b.keyShares[0].group != group {
		return fail(AlertIllegalParameter, "second ClientHello must carry exactly one key share, for %s", GroupName(group))
	}
	if !validPeerShare(group, b.keyShares[0].data) {
		return fail(AlertIllegalParameter, "invalid key share in second ClientHello")
	}
	if !offersSuite(b.versions, versionTLS13) || a.serverName != b.serverName {
		return fail(AlertIllegalParameter, "second ClientHello changed supported_versions or server_name")
	}
	return nil
}

func (c *Conn) pickCertificate(ch *clientHello) (*Certificate, uint16, error) {
	var cands []*Certificate
	if c.cfg.GetCertificate != nil {
		cert, err := c.cfg.GetCertificate(ch.serverName)
		if err != nil {
			return nil, 0, fail(AlertUnrecognizedName, "no certificate for %q: %v", ch.serverName, err)
		}
		cands = append(cands, cert)
	}
	for i := range c.cfg.Certificates {
		cands = append(cands, &c.cfg.Certificates[i])
	}
	for _, cert := range cands {
		leaf, err := cert.parseLeaf()
		if err != nil {
			continue
		}
		if alg, ok := pickSigAlg(leaf.PublicKey, ch.sigAlgs); ok {
			return cert, alg, nil
		}
	}
	return nil, 0, fail(AlertHandshakeFailure, "no certificate matches the client's signature algorithms")
}

func (c *Conn) readClientAuth() error {
	msg, err := c.readHS(hsCertificate)
	if err != nil {
		return err
	}
	cm, err := parseCertificate(msg)
	if err != nil {
		return err
	}
	if len(cm.context) != 0 {
		return fail(AlertIllegalParameter, "client Certificate context must be empty")
	}
	if len(cm.certs) == 0 {
		if c.cfg.ClientAuth == RequireClientCert {
			return fail(AlertCertificateRequired, "client did not send a certificate")
		}
		return nil
	}
	certs := make([]*x509.Certificate, len(cm.certs))
	for i, der := range cm.certs {
		if certs[i], err = x509.ParseCertificate(der); err != nil {
			return fail(AlertBadCertificate, "cannot parse client certificate %d: %v", i, err)
		}
	}
	c.state.PeerCertificates = certs
	inter := x509.NewCertPool()
	for _, ic := range certs[1:] {
		inter.AddCert(ic)
	}
	chains, err := certs[0].Verify(x509.VerifyOptions{Roots: c.cfg.ClientCAs, Intermediates: inter,
		CurrentTime: c.cfg.now(), KeyUsages: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth}})
	if err != nil {
		return certErr(err)
	}
	c.state.VerifiedChains = chains
	msg, err = c.readHS(hsCertificateVerify)
	if err != nil {
		return err
	}
	cv, err := parseCertificateVerify(msg)
	if err != nil {
		return err
	}
	if !offersSuite(supportedSigAlgs, cv.alg) {
		return fail(AlertIllegalParameter, "client used signature scheme %s which we did not offer", SigAlgName(cv.alg))
	}
	return verifyCertVerify(certs[0].PublicKey, cv.alg, signedContent(false, c.transcriptHashBefore()), cv.sig)
}

func (c *Conn) sendTicket() error {
	nonce := []byte{0}
	ageAddB := make([]byte, 4)
	if _, err := io.ReadFull(c.cfg.rand(), ageAddB); err != nil {
		return err
	}
	ageAdd := uint32(ageAddB[0])<<24 | uint32(ageAddB[1])<<16 | uint32(ageAddB[2])<<8 | uint32(ageAddB[3])
	st := &sessionState{suite: c.suite.id, created: c.cfg.now(), ageAdd: ageAdd,
		psk: c.suite.resumptionPSK(c.resMaster, nonce), serverName: c.state.ServerName, alpn: c.state.NegotiatedProtocol}
	t, err := sealTicket(c.cfg.sealKey(), c.cfg.rand(), st)
	if err != nil {
		return err
	}
	m := &newSessionTicket{lifetime: uint32(ticketLifetime / time.Second), ageAdd: ageAdd, nonce: nonce, ticket: t}
	msg := m.marshal()
	c.trace("send", "handshake", "NewSessionTicket", DescribeHandshake(msg), len(msg))
	return c.writeRecordLocked(recHandshake, msg)
}
