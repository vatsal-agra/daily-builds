"""A real file-transfer application built on top of MiniTCPSocket, proving
the transport's correctness under adversarial network conditions with an
end-to-end SHA-256 integrity check.
"""
import hashlib
import time

from .socket_ import MiniTCPSocket

CHUNK = 4096


def send_file(local_addr, peer_addr, data, event_log=None, name="sender", timeout=60.0):
    sock = MiniTCPSocket(local_addr, event_log=event_log, name=name)
    t0 = time.monotonic()
    sock.connect(peer_addr, timeout=timeout)
    for i in range(0, len(data), CHUNK):
        sock.send(data[i:i + CHUNK])
    sock.close(timeout=timeout)
    elapsed = time.monotonic() - t0
    return {
        "bytes_sent": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "elapsed_seconds": elapsed,
    }


def receive_file(local_addr, event_log=None, name="receiver", timeout=60.0):
    sock = MiniTCPSocket(local_addr, event_log=event_log, name=name)
    sock.listen()
    sock.accept(timeout=timeout)
    t0 = time.monotonic()
    data = sock.recv_all(timeout=timeout)
    sock.close(timeout=timeout)
    elapsed = time.monotonic() - t0
    return {
        "bytes_received": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "elapsed_seconds": elapsed,
        "data": data,
    }
