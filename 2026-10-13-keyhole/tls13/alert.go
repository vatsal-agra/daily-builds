package tls13

import "fmt"

// Alert is a TLS alert description (RFC 8446 §6).
type Alert uint8

const (
	AlertCloseNotify                  Alert = 0
	AlertUnexpectedMessage            Alert = 10
	AlertBadRecordMAC                 Alert = 20
	AlertRecordOverflow               Alert = 22
	AlertHandshakeFailure             Alert = 40
	AlertBadCertificate               Alert = 42
	AlertUnsupportedCertificate       Alert = 43
	AlertCertificateRevoked           Alert = 44
	AlertCertificateExpired           Alert = 45
	AlertCertificateUnknown           Alert = 46
	AlertIllegalParameter             Alert = 47
	AlertUnknownCA                    Alert = 48
	AlertAccessDenied                 Alert = 49
	AlertDecodeError                  Alert = 50
	AlertDecryptError                 Alert = 51
	AlertProtocolVersion              Alert = 70
	AlertInsufficientSecurity         Alert = 71
	AlertInternalError                Alert = 80
	AlertInappropriateFallback        Alert = 86
	AlertUserCanceled                 Alert = 90
	AlertMissingExtension             Alert = 109
	AlertUnsupportedExtension         Alert = 110
	AlertUnrecognizedName             Alert = 112
	AlertBadCertificateStatusResponse Alert = 113
	AlertUnknownPSKIdentity           Alert = 115
	AlertCertificateRequired          Alert = 116
	AlertNoApplicationProtocol        Alert = 120
)

var alertNames = map[Alert]string{
	0: "close_notify", 10: "unexpected_message", 20: "bad_record_mac", 22: "record_overflow",
	40: "handshake_failure", 42: "bad_certificate", 43: "unsupported_certificate",
	44: "certificate_revoked", 45: "certificate_expired", 46: "certificate_unknown",
	47: "illegal_parameter", 48: "unknown_ca", 49: "access_denied", 50: "decode_error",
	51: "decrypt_error", 70: "protocol_version", 71: "insufficient_security", 80: "internal_error",
	86: "inappropriate_fallback", 90: "user_canceled", 109: "missing_extension",
	110: "unsupported_extension", 112: "unrecognized_name", 113: "bad_certificate_status_response",
	115: "unknown_psk_identity", 116: "certificate_required", 120: "no_application_protocol",
}

func (a Alert) String() string {
	if n, ok := alertNames[a]; ok {
		return n
	}
	return fmt.Sprintf("alert(%d)", uint8(a))
}

// AlertError is returned when the peer sent us a fatal alert.
type AlertError struct{ Alert Alert }

func (e *AlertError) Error() string { return "tls13: remote error: " + e.Alert.String() }

// ProtocolError is a local failure; Alert is what we send the peer.
type ProtocolError struct {
	Alert Alert
	Msg   string
}

func (e *ProtocolError) Error() string {
	return fmt.Sprintf("tls13: %s (sent alert %s)", e.Msg, e.Alert)
}

func fail(a Alert, format string, args ...any) error {
	return &ProtocolError{Alert: a, Msg: fmt.Sprintf(format, args...)}
}
