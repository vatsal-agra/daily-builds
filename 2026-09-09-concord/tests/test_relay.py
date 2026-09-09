#!/usr/bin/env python3
"""test_relay.py — unit tests for server/relay.py against a REAL running
instance (spawned in a background thread on a scratch port; no mocks). Uses
raw sockets to read the SSE stream progressively, since the stream is
intentionally held open indefinitely and http.client isn't a great fit for
"read frames as they arrive, then stop".
"""
import json
import socket
import threading
import time
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server'))
import relay  # noqa: E402


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class RawHttp:
    """Minimal raw-socket HTTP client, deliberately not using
    urllib/http.client for the SSE endpoint: we need to read exactly as
    many bytes as have arrived so far without blocking forever waiting for
    a Content-Length or connection close that will never come."""

    def __init__(self, host, port):
        self.host = host
        self.port = port

    def request(self, method, path, body=None, headers=None):
        sock = socket.create_connection((self.host, self.port), timeout=5)
        headers = dict(headers or {})
        data = b''
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Length'] = str(len(data))
            headers['Content-Type'] = 'application/json'
        lines = ['%s %s HTTP/1.1' % (method, path), 'Host: %s' % self.host, 'Connection: close']
        for k, v in headers.items():
            lines.append('%s: %s' % (k, v))
        req = ('\r\n'.join(lines) + '\r\n\r\n').encode('utf-8') + data
        sock.sendall(req)
        buf = b''
        sock.settimeout(3)
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
        except socket.timeout:
            pass
        sock.close()
        head, _, rest = buf.partition(b'\r\n\r\n')
        status_line = head.split(b'\r\n', 1)[0].decode('utf-8')
        status = int(status_line.split(' ')[1])
        return status, rest.decode('utf-8', errors='replace')

    def open_sse(self, path):
        """Returns a live socket with the request already sent and headers
        already consumed; caller reads frames off it."""
        sock = socket.create_connection((self.host, self.port), timeout=5)
        req = 'GET %s HTTP/1.1\r\nHost: %s\r\n\r\n' % (path, self.host)
        sock.sendall(req.encode('utf-8'))
        sock.settimeout(5)
        buf = b''
        while b'\r\n\r\n' not in buf:
            buf += sock.recv(4096)
        # buf may already contain part of the body past the header
        # terminator; keep it, the caller's frame reader picks up from here.
        head, _, rest = buf.partition(b'\r\n\r\n')
        return sock, rest.decode('utf-8', errors='replace')


def read_sse_events(sock, leftover, count, timeout=5.0):
    """Reads `count` more SSE 'op'/'ready' frames (ignoring heartbeat
    comments) starting from any leftover bytes already read off `sock`."""
    events = []
    buf = leftover
    deadline = time.time() + timeout
    while len(events) < count and time.time() < deadline:
        idx = buf.find('\n\n')
        if idx == -1:
            sock.settimeout(max(0.1, deadline - time.time()))
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk.decode('utf-8', errors='replace')
            continue
        frame, buf = buf[:idx], buf[idx + 2:]
        if not frame.strip() or frame.startswith(':'):
            continue
        ev_line = [l for l in frame.split('\n') if l.startswith('event: ')]
        data_line = [l for l in frame.split('\n') if l.startswith('data: ')]
        if not ev_line or not data_line:
            continue
        events.append((ev_line[0][len('event: '):], json.loads(data_line[0][len('data: '):])))
    return events, buf


class RelayTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = relay.ThreadingHTTPServer(('127.0.0.1', cls.port), relay.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.client = RawHttp('127.0.0.1', cls.port)
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def unique_doc(self):
        relay.STORE.docs.clear()  # test isolation: every test gets a clean store
        return 'doc-%s' % self.id().split('.')[-1]

    # ---- static files ----
    def test_static_files_served(self):
        status, _ = self.client.request('GET', '/')
        self.assertEqual(status, 200)
        status, body = self.client.request('GET', '/crdt.js')
        self.assertEqual(status, 200)
        self.assertIn('RGA', body)

    def test_unknown_path_404(self):
        status, _ = self.client.request('GET', '/nonexistent')
        self.assertEqual(status, 404)

    # ---- doc id validation ----
    def test_invalid_doc_id_rejected(self):
        # A single ".." path segment matches the route regex ([^/]+) but
        # must fail Concord's own doc-id character validation.
        status, _ = self.client.request('POST', '/doc/..%2Fetc/ops', {'siteId': 's', 'ops': []})
        self.assertEqual(status, 400)
        status, _ = self.client.request('POST', '/doc/has%20space/ops', {'siteId': 's', 'ops': []})
        self.assertEqual(status, 400)
        # A doc id spanning multiple path segments doesn't match the route
        # at all (not a traversal risk either way — doc_id is only ever
        # used as an in-memory dict key, never a filesystem path — but the
        # request should still fail cleanly, not 200).
        status, _ = self.client.request('POST', '/doc/../../etc/ops', {'siteId': 's', 'ops': []})
        self.assertNotEqual(status, 200)

    # ---- op validation ----
    def test_well_formed_op_accepted(self):
        doc = self.unique_doc()
        op = {'type': 'insert', 'id': [1, 'site1'], 'value': 'x', 'leftId': None}
        status, body = self.client.request('POST', '/doc/%s/ops' % doc, {'siteId': 'site1', 'ops': [op]})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)['seqs'], [1])

    def test_malformed_op_rejected(self):
        doc = self.unique_doc()
        bad_ops = [
            {'type': 'insert'},  # missing id/value
            {'type': 'insert', 'id': ['not-an-int', 'site1'], 'value': 'x', 'leftId': None},
            {'type': 'insert', 'id': [1, 'site1'], 'value': 'toolong', 'leftId': None},
            {'type': 'insert', 'id': [1, 'site1'], 'value': 'x', 'leftId': 'not-a-list'},
            {'type': 'delete', 'id': [1]},  # wrong arity
            {'type': 'bogus', 'id': [1, 's']},
            {'id': [1, 's'], 'value': 'x'},  # missing type
        ]
        for bad in bad_ops:
            status, body = self.client.request('POST', '/doc/%s/ops' % doc, {'siteId': 'site1', 'ops': [bad]})
            self.assertEqual(status, 400, 'expected 400 for %r, got %s: %s' % (bad, status, body))

    def test_partial_batch_is_atomic_not_partially_broadcast(self):
        """Regression test for a real bug found during adversarial review:
        an earlier version of the handler validated ops one at a time,
        appending/broadcasting each valid one as it went, and only
        returned 400 once it hit the first invalid op later in the list —
        so a client got told "your whole request failed" while everyone
        else had already silently received part of it. The whole batch
        must be validated before ANY of it is appended."""
        doc = self.unique_doc()
        good = {'type': 'insert', 'id': [1, 'site1'], 'value': 'x', 'leftId': None}
        bad = {'type': 'insert', 'id': [2, 'site1']}  # missing value
        status, body = self.client.request('POST', '/doc/%s/ops' % doc, {'siteId': 'site1', 'ops': [good, bad]})
        self.assertEqual(status, 400, body)
        # Nothing from this rejected batch should have reached the log.
        status, snap_body = self.client.request('GET', '/doc/%s/snapshot' % doc)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(snap_body)['log'], [], 'a rejected batch leaked a partial append')

    def test_cursor_validation(self):
        doc = self.unique_doc()
        status, _ = self.client.request('POST', '/doc/%s/cursor' % doc, {'siteId': 's1', 'index': 'not-an-int'})
        self.assertEqual(status, 400)
        status, _ = self.client.request('POST', '/doc/%s/cursor' % doc, {'siteId': '', 'index': 3})
        self.assertEqual(status, 400)
        status, _ = self.client.request('POST', '/doc/%s/cursor' % doc, {'siteId': 's1', 'index': 3})
        self.assertEqual(status, 200)

    # ---- SSE backlog + live broadcast ----
    def test_sse_backlog_replay_and_live_broadcast(self):
        doc = self.unique_doc()
        op1 = {'type': 'insert', 'id': [1, 'site1'], 'value': 'a', 'leftId': None}
        status, _ = self.client.request('POST', '/doc/%s/ops' % doc, {'siteId': 'site1', 'ops': [op1]})
        self.assertEqual(status, 200)

        sock, leftover = self.client.open_sse('/doc/%s/events?since=0' % doc)
        events, leftover = read_sse_events(sock, leftover, 2)  # backlog op + 'ready'
        kinds = [e[0] for e in events]
        self.assertIn('op', kinds)
        self.assertIn('ready', kinds)
        backlog_op = [e for e in events if e[0] == 'op'][0][1]
        self.assertEqual(backlog_op['op']['op']['value'], 'a')

        op2 = {'type': 'insert', 'id': [2, 'site1'], 'value': 'b', 'leftId': [1, 'site1']}
        self.client.request('POST', '/doc/%s/ops' % doc, {'siteId': 'site1', 'ops': [op2]})
        live_events, leftover = read_sse_events(sock, leftover, 1)
        self.assertEqual(len(live_events), 1, 'expected the live op to arrive over the open SSE connection')
        self.assertEqual(live_events[0][1]['op']['op']['value'], 'b')
        sock.close()

    def test_late_joiner_since_skips_already_seen_backlog(self):
        doc = self.unique_doc()
        for i in range(3):
            op = {'type': 'insert', 'id': [i + 1, 'site1'], 'value': 'x', 'leftId': ([i, 'site1'] if i else None)}
            self.client.request('POST', '/doc/%s/ops' % doc, {'siteId': 'site1', 'ops': [op]})
        sock, leftover = self.client.open_sse('/doc/%s/events?since=2' % doc)
        events, leftover = read_sse_events(sock, leftover, 2)  # 1 backlog op (seq 3) + ready
        op_events = [e for e in events if e[0] == 'op']
        self.assertEqual(len(op_events), 1, 'since=2 should only replay seq 3, not the first two again')
        self.assertEqual(op_events[0][1]['seq'], 3)
        sock.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
