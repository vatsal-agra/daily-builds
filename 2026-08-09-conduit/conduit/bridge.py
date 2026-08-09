"""A TCP <-> Conduit bridge — the piece that lets a real, unmodified TCP
client (curl, in particular) talk to a Conduit-backed server.

curl only ever speaks real TCP; it has no idea what Conduit is. The
bridge listens on a real TCP port. For each TCP connection it accepts, it
opens a *new* Conduit connection to the target and copies raw bytes in
both directions until either side closes — a plain byte-for-byte relay,
nothing HTTP-aware about it. Whatever travels between curl and the
Conduit-backed HTTP server therefore genuinely crosses Conduit's
reliability layer (and, in the oracle test, NetworkSimulator's loss/
reorder/duplication) end to end.

    curl <--TCP--> [TcpToConduitBridge] <--Conduit (over UDP, via netsim)--> Listener/HttpServer
"""

import socket
import threading

from conduit.api import connect as conduit_connect


class TcpToConduitBridge:
    def __init__(self, tcp_bind_addr, conduit_target_addr, trace=None):
        self._tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._tcp_sock.bind(tcp_bind_addr)
        self._tcp_sock.listen(16)
        self._tcp_sock.settimeout(0.5)
        self._target = conduit_target_addr
        self._trace = trace
        self._stop = threading.Event()
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True, name="bridge-accept")
        self._accept_thread.start()

    @property
    def local_addr(self):
        return self._tcp_sock.getsockname()

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                tcp_conn, _addr = self._tcp_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(target=self._serve_one, args=(tcp_conn,), daemon=True, name="bridge-conn")
            t.start()

    def _serve_one(self, tcp_conn):
        try:
            conduit_conn = conduit_connect(self._target, trace=self._trace, timeout=10.0)
        except Exception:
            tcp_conn.close()
            return

        done = threading.Event()

        def tcp_to_conduit():
            try:
                while True:
                    data = tcp_conn.recv(8192)
                    if not data:
                        break
                    conduit_conn.send(data)
            except OSError:
                pass
            finally:
                done.set()

        def conduit_to_tcp():
            try:
                while True:
                    data = conduit_conn.recv(8192, timeout=30.0)
                    if not data:
                        break
                    tcp_conn.sendall(data)
            except Exception:
                pass
            finally:
                done.set()

        t1 = threading.Thread(target=tcp_to_conduit, daemon=True)
        t2 = threading.Thread(target=conduit_to_tcp, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=30.0)
        t2.join(timeout=15.0)

        try:
            conduit_conn.close()
        except Exception:
            pass
        try:
            tcp_conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        tcp_conn.close()

    def close(self):
        self._stop.set()
        self._tcp_sock.close()
