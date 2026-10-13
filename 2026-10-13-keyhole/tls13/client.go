package tls13

import (
	"crypto/x509"
	"errors"
	"io"
	"net"
	"time"
)

func isIPLiteral(s string) bool { return net.ParseIP(s) != nil }

func (c *Conn) newRandom() ([]byte, error) {
	b := make([]byte, 32)
	_, err := io.ReadFull(c.cfg.rand(), b)
	return b, err
}

func offersSuite(ids []uint16, id uint16) bool {
	for _, x := range ids {
		if x == id {
			return true
		}
	}
	return false
}

func (c *Conn) clientHandshake() error {
	cfg := c.cfg
	suiteList := cfg.suites()
	if len(suiteList) == 0 {
		return errors.New("tls13: no usable cipher suites configured")
	}
	groups := cfg.groups()
	if len(groups) == 0 {
		return errors.New("tls13: no usable groups configured")
	}
	if cfg.ServerName == "" && !cfg.InsecureSkipVerify {
		return errors.New("tls13: Config.ServerName is required unless InsecureSkipVerify is set")
	}
	ch := &clientHello{compression: []byte{0}, groups: groups, sigAlgs: supportedSigAlgs,
		versions: []uint16{versionTLS13}, pskModes: []uint8{pskModeDHE}, alpn: cfg.NextProtos}
	for _, s := range suiteList {
		ch.suites = append(ch.suites, s.id)
	}
	var err error
	if ch.random, err = c.newRandom(); err != nil {
		return err
	}
	if ch.sessionID, err = c.newRandom(); err != nil { // legacy_session_id for middlebox compatibility
		return err
	}
	c.clientRandom = ch.random
	if cfg.ServerName != "" && !isIPLiteral(cfg.ServerName) {
		ch.serverName = cfg.ServerName
	}
	for _, p := range cfg.NextProtos {
		if p == "" || len(p) > 255 {
			return errors.New("tls13: invalid ALPN protocol name")
		}
	}

	kx, err := newKeyExchange(cfg.rand(), groups[0])
	if err != nil {
		return err
	}
	ch.keyShares = []keyShareEntry{{kx.group, kx.public()}}

	// Resumption candidate.
	var sess *ClientSession
	if cfg.SessionCache != nil && cfg.ServerName != "" {
		if s := cfg.SessionCache.Take(cfg.ServerName, cfg.now()); s != nil && offersSuite(ch.suites, s.Suite) {
			if chains, ok := c.reverifySession(s); ok {
				sess = s
				c.resumeChains = chains
			}
		}
	}
	if err := c.sealClientHello(ch, sess); err != nil {
		return err
	}
	if err := c.sendHS(ch.raw); err != nil {
		return err
	}
	if err := c.flushLocked(); err != nil {
		return err
	}

	// ---- ServerHello (or HelloRetryRequest) ----
	msg, err := c.readHS(hsServerHello)
	if err != nil {
		return err
	}
	sh, err := parseServerHello(msg)
	if err != nil {
		return err
	}
	ccsSent := false
	if sh.hrr {
		c.state.HelloRetryRequest = true
		if err := c.checkServerHello(sh, ch); err != nil {
			return err
		}
		c.suite = suiteByID(sh.suite)
		// Transcript replaced by message_hash(CH1) || HRR.
		hrrMsg := append([]byte(nil), c.transcript[c.prevLen:]...)
		ch1 := c.transcript[:c.prevLen]
		c.transcript = hsFrame(hsMessageHash, c.suite.sum(ch1))
		c.transcript = append(c.transcript, hrrMsg...)
		c.prevLen = len(c.transcript) - len(hrrMsg)

		if sh.keyShare.group != 0 && sh.hasKeyShr {
			if sh.keyShare.group == kx.group || !offersSuiteGroup(groups, sh.keyShare.group) {
				return fail(AlertIllegalParameter, "HelloRetryRequest selects unusable group %s", GroupName(sh.keyShare.group))
			}
			if kx, err = newKeyExchange(cfg.rand(), sh.keyShare.group); err != nil {
				return err
			}
			ch.keyShares = []keyShareEntry{{kx.group, kx.public()}}
		} else if len(sh.cookie) == 0 {
			return fail(AlertIllegalParameter, "HelloRetryRequest changes nothing")
		}
		ch.cookie = sh.cookie
		if sess != nil && suiteByID(sess.Suite).hashLen() != c.suite.hashLen() {
			sess = nil // PSK hash no longer matches the negotiated suite: drop it
			ch.psks, ch.binders = nil, nil
		}
		if err := c.sealClientHello(ch, sess); err != nil {
			return err
		}
		if err := c.sendCCS(); err != nil {
			return err
		}
		ccsSent = true
		if err := c.sendHS(ch.raw); err != nil {
			return err
		}
		if err := c.flushLocked(); err != nil {
			return err
		}
		if msg, err = c.readHS(hsServerHello); err != nil {
			return err
		}
		if sh, err = parseServerHello(msg); err != nil {
			return err
		}
		if sh.hrr {
			return fail(AlertUnexpectedMessage, "second HelloRetryRequest")
		}
	}
	if err := c.checkServerHello(sh, ch); err != nil {
		return err
	}
	if c.suite != nil && c.suite.id != sh.suite {
		return fail(AlertIllegalParameter, "ServerHello changed the cipher suite after HelloRetryRequest")
	}
	c.suite = suiteByID(sh.suite)
	if !sh.hasKeyShr || sh.keyShare.group != kx.group {
		return fail(AlertIllegalParameter, "ServerHello key share group does not match what we offered")
	}
	ecdhe, err := kx.shared(sh.keyShare.data)
	if err != nil {
		return err
	}
	var psk []byte
	if sh.pskSelect >= 0 {
		if sess == nil || sh.pskSelect != 0 {
			return fail(AlertIllegalParameter, "server selected a PSK we did not offer")
		}
		if suiteByID(sess.Suite).hashLen() != c.suite.hashLen() {
			return fail(AlertIllegalParameter, "PSK hash does not match the selected cipher suite")
		}
		psk = sess.PSK
		c.state.DidResume = true
		c.state.PeerCertificates = sess.PeerChain
		c.state.VerifiedChains = c.resumeChains
	}
	c.state.KeyShareGroup = kx.group
	c.state.CipherSuite = c.suite.id
	c.state.Version = versionTLS13
	c.state.ServerName = cfg.ServerName

	early := c.suite.earlySecret(psk)
	hsSecret := c.suite.handshakeSecret(early, ecdhe)
	th := c.transcriptHash()
	cHS := deriveSecret(c.suite.hash, hsSecret, "c hs traffic", th)
	sHS := deriveSecret(c.suite.hash, hsSecret, "s hs traffic", th)
	c.keyLog("CLIENT_HANDSHAKE_TRAFFIC_SECRET", cHS)
	c.keyLog("SERVER_HANDSHAKE_TRAFFIC_SECRET", sHS)
	if err := c.setReadSecret(sHS, "server handshake traffic"); err != nil {
		return err
	}
	if err := c.setWriteSecret(cHS, "client handshake traffic"); err != nil {
		return err
	}
	masterSecret := c.suite.masterSecret(hsSecret)

	// ---- EncryptedExtensions ----
	msg, err = c.readHS(hsEncryptedExtensions)
	if err != nil {
		return err
	}
	ee, err := parseEncryptedExtensions(msg)
	if err != nil {
		return err
	}
	if ee.hasALPN {
		if len(cfg.NextProtos) == 0 {
			return fail(AlertUnsupportedExtension, "server selected ALPN %q but we offered none", ee.alpn)
		}
		if !contains(cfg.NextProtos, ee.alpn) {
			return fail(AlertIllegalParameter, "server selected ALPN %q which we did not offer", ee.alpn)
		}
		c.state.NegotiatedProtocol = ee.alpn
	}
	if ee.serverName && ch.serverName == "" {
		return fail(AlertUnsupportedExtension, "unsolicited server_name acknowledgement")
	}

	// ---- Certificate flight (absent on resumption) ----
	var certReq *certificateRequest
	if psk == nil {
		msg, err = c.readHS(0)
		if err != nil {
			return err
		}
		if msg[0] == hsCertificateRequest {
			if certReq, err = parseCertificateRequest(msg); err != nil {
				return err
			}
			if len(certReq.context) != 0 {
				return fail(AlertIllegalParameter, "CertificateRequest context must be empty during the handshake")
			}
			if msg, err = c.readHS(hsCertificate); err != nil {
				return err
			}
		} else if msg[0] != hsCertificate {
			return fail(AlertUnexpectedMessage, "got %s, expected Certificate", HandshakeName(msg[0]))
		}
		cm, err := parseCertificate(msg)
		if err != nil {
			return err
		}
		if len(cm.context) != 0 {
			return fail(AlertIllegalParameter, "server Certificate has a non-empty request context")
		}
		leaf, err := c.verifyServerChain(cm)
		if err != nil {
			return err
		}
		msg, err = c.readHS(hsCertificateVerify)
		if err != nil {
			return err
		}
		cv, err := parseCertificateVerify(msg)
		if err != nil {
			return err
		}
		if !offersSuite(supportedSigAlgs, cv.alg) {
			return fail(AlertIllegalParameter, "server used signature scheme %s which we did not offer", SigAlgName(cv.alg))
		}
		if err := verifyCertVerify(leaf.PublicKey, cv.alg, signedContent(true, c.transcriptHashBefore()), cv.sig); err != nil {
			return err
		}
		c.state.SignatureAlgorithm = cv.alg
	}

	// ---- server Finished ----
	msg, err = c.readHS(hsFinished)
	if err != nil {
		return err
	}
	if want := c.suite.finishedMAC(sHS, c.transcriptHashBefore()); len(msg)-4 != len(want) || !ctEqual(msg[4:], want) {
		return fail(AlertDecryptError, "server Finished verify_data is wrong")
	}
	th = c.transcriptHash() // CH..server Finished
	cAP := deriveSecret(c.suite.hash, masterSecret, "c ap traffic", th)
	sAP := deriveSecret(c.suite.hash, masterSecret, "s ap traffic", th)
	c.exporterMaster = deriveSecret(c.suite.hash, masterSecret, "exp master", th)
	c.keyLog("CLIENT_TRAFFIC_SECRET_0", cAP)
	c.keyLog("SERVER_TRAFFIC_SECRET_0", sAP)
	c.keyLog("EXPORTER_SECRET", c.exporterMaster)
	if err := c.setReadSecret(sAP, "server application traffic"); err != nil {
		return err
	}

	// ---- client flight ----
	if !ccsSent {
		if err := c.sendCCS(); err != nil {
			return err
		}
	}
	if certReq != nil {
		if err := c.sendClientAuth(certReq); err != nil {
			return err
		}
	}
	fin := hsFrame(hsFinished, c.suite.finishedMAC(cHS, c.transcriptHash()))
	if err := c.sendHS(fin); err != nil {
		return err
	}
	c.resMaster = deriveSecret(c.suite.hash, masterSecret, "res master", c.transcriptHash())
	if err := c.setWriteSecret(cAP, "client application traffic"); err != nil {
		return err
	}
	return nil
}

func offersSuiteGroup(gs []uint16, g uint16) bool { return offersSuite(gs, g) }

func contains(l []string, s string) bool {
	for _, x := range l {
		if x == s {
			return true
		}
	}
	return false
}

// sealClientHello marshals ch, computing the PSK binder when resuming.
func (c *Conn) sealClientHello(ch *clientHello, sess *ClientSession) error {
	if sess == nil {
		ch.psks, ch.binders = nil, nil
		ch.marshal()
		return nil
	}
	s := suiteByID(sess.Suite)
	age := uint32(c.cfg.now().Sub(sess.Received)/time.Millisecond) + sess.AgeAdd
	ch.psks = []pskIdentity{{sess.Ticket, age}}
	ch.binders = [][]byte{make([]byte, s.hashLen())}
	ch.marshal()
	early := s.earlySecret(sess.PSK)
	binderKey := deriveSecret(s.hash, early, "res binder", s.sum(nil))
	partial := append(append([]byte(nil), c.transcript...), ch.raw[:ch.bindersStart]...)
	ch.binders = [][]byte{s.finishedMAC(binderKey, s.sum(partial))}
	ch.marshal()
	return nil
}

// checkServerHello validates fields common to ServerHello and HelloRetryRequest.
func (c *Conn) checkServerHello(sh *serverHello, ch *clientHello) error {
	if sh.version != versionTLS13 {
		if len(sh.random) == 32 && (string(sh.random[24:]) == string(downgradeTLS12) || string(sh.random[24:]) == string(downgradeTLS11)) {
			return fail(AlertIllegalParameter, "server random carries a TLS downgrade sentinel")
		}
		return fail(AlertProtocolVersion, "server does not support TLS 1.3 (selected version 0x%04x)", sh.version)
	}
	if sh.legacyVer != versionTLS12 {
		return fail(AlertIllegalParameter, "ServerHello legacy_version is 0x%04x", sh.legacyVer)
	}
	if string(sh.sessionID) != string(ch.sessionID) {
		return fail(AlertIllegalParameter, "ServerHello did not echo legacy_session_id")
	}
	if !offersSuite(ch.suites, sh.suite) {
		return fail(AlertIllegalParameter, "server selected cipher suite 0x%04x which we did not offer", sh.suite)
	}
	if sh.hrr && sh.pskSelect >= 0 {
		return fail(AlertIllegalParameter, "HelloRetryRequest carries a pre_shared_key")
	}
	return nil
}

// verifyServerChain verifies the chain and hostname, returning the leaf.
func (c *Conn) verifyServerChain(cm *certificateMsg) (*x509.Certificate, error) {
	if len(cm.certs) == 0 {
		return nil, fail(AlertBadCertificate, "server sent no certificate")
	}
	certs := make([]*x509.Certificate, len(cm.certs))
	for i, der := range cm.certs {
		cert, err := x509.ParseCertificate(der)
		if err != nil {
			return nil, fail(AlertBadCertificate, "cannot parse certificate %d: %v", i, err)
		}
		certs[i] = cert
	}
	c.state.PeerCertificates = certs
	if !c.cfg.InsecureSkipVerify {
		inter := x509.NewCertPool()
		for _, ic := range certs[1:] {
			inter.AddCert(ic)
		}
		chains, err := certs[0].Verify(x509.VerifyOptions{
			Roots: c.cfg.RootCAs, Intermediates: inter, DNSName: c.cfg.ServerName,
			CurrentTime: c.cfg.now(), KeyUsages: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		})
		if err != nil {
			return nil, certErr(err)
		}
		c.state.VerifiedChains = chains
	}
	return certs[0], nil
}

// certErr maps an x509 failure to the closest TLS alert.
func certErr(err error) error {
	var inv x509.CertificateInvalidError
	var unk x509.UnknownAuthorityError
	var host x509.HostnameError
	switch {
	case errors.As(err, &inv):
		if inv.Reason == x509.Expired {
			return fail(AlertCertificateExpired, "certificate verification: %v", err)
		}
		return fail(AlertBadCertificate, "certificate verification: %v", err)
	case errors.As(err, &unk):
		return fail(AlertUnknownCA, "certificate verification: %v", err)
	case errors.As(err, &host):
		return fail(AlertBadCertificate, "certificate verification: %v", err)
	}
	return fail(AlertBadCertificate, "certificate verification: %v", err)
}

func (c *Conn) sendClientAuth(req *certificateRequest) error {
	cert := c.cfg.ClientCertificate
	if cert == nil || len(cert.Chain) == 0 {
		return c.sendHS((&certificateMsg{context: req.context}).marshal())
	}
	leaf, err := cert.parseLeaf()
	if err != nil {
		return err
	}
	alg, ok := pickSigAlg(leaf.PublicKey, req.sigAlgs)
	if !ok {
		// cannot satisfy the server's constraints: send an empty Certificate
		return c.sendHS((&certificateMsg{context: req.context}).marshal())
	}
	if err := c.sendHS((&certificateMsg{context: req.context, certs: cert.Chain}).marshal()); err != nil {
		return err
	}
	sig, err := signCertVerify(c.cfg.rand(), cert.Key, alg, signedContent(false, c.transcriptHash()))
	if err != nil {
		return err
	}
	return c.sendHS((&certificateVerify{alg: alg, sig: sig}).marshal())
}

// parseLeaf parses the leaf on every call: Certificate values are shared between connections, so
// caching into the struct would be a data race.
func (cert *Certificate) parseLeaf() (*x509.Certificate, error) {
	if len(cert.Chain) == 0 || cert.Key == nil {
		return nil, errors.New("tls13: certificate needs a chain and a private key")
	}
	return x509.ParseCertificate(cert.Chain[0])
}

// reverifySession decides whether a cached ticket may be offered by *this* configuration. A session
// is a bearer credential for whatever authentication its first handshake did, so a verifying
// client may only reuse one whose server certificate it would accept right now (same roots, name
// and clock) — otherwise a cache shared with an InsecureSkipVerify client would bypass verification.
func (c *Conn) reverifySession(s *ClientSession) ([][]*x509.Certificate, bool) {
	if c.cfg.InsecureSkipVerify {
		return nil, true
	}
	if !s.Verified || len(s.PeerChain) == 0 {
		return nil, false
	}
	inter := x509.NewCertPool()
	for _, ic := range s.PeerChain[1:] {
		inter.AddCert(ic)
	}
	chains, err := s.PeerChain[0].Verify(x509.VerifyOptions{Roots: c.cfg.RootCAs, Intermediates: inter, DNSName: c.cfg.ServerName,
		CurrentTime: c.cfg.now(), KeyUsages: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}})
	return chains, err == nil
}

// storeTicket records a NewSessionTicket for later resumption.
func (c *Conn) storeTicket(m *newSessionTicket) {
	c.tickets.Add(1)
	if c.cfg.SessionCache == nil || c.cfg.ServerName == "" || m.lifetime == 0 || c.resMaster == nil {
		return
	}
	life := time.Duration(m.lifetime) * time.Second
	if life > 7*24*time.Hour {
		life = 7 * 24 * time.Hour
	}
	c.cfg.SessionCache.Put(c.cfg.ServerName, &ClientSession{
		Ticket: m.ticket, Suite: c.suite.id, PSK: c.suite.resumptionPSK(c.resMaster, m.nonce),
		AgeAdd: m.ageAdd, Received: c.cfg.now(), Lifetime: life, ALPN: c.state.NegotiatedProtocol,
		Verified: !c.cfg.InsecureSkipVerify && len(c.state.VerifiedChains) > 0, PeerChain: c.state.PeerCertificates,
	})
}
