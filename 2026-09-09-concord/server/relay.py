#!/usr/bin/env python3
"""relay.py — Concord's server: a dumb broadcast hub, not a CRDT authority.

Deliberately: this server never parses, orders, or resolves a CRDT
operation. It appends whatever bytes a client POSTs to a per-document
append-only log (so a client joining late, or reconnecting after being
offline, can catch up), and rebroadcasts every op to every other subscriber
of that document over a hand-rolled Server-Sent-Events stream. All of the
actual conflict-free-replication logic lives in client/crdt.js, which is the
point of a CRDT: replicas don't need a smart middleman to agree with each
other.

Pure Python 3 stdlib only (`http.server`, `threading`, `queue`, `json`) — no
Flask, no `websockets`, no third-party deps, matching this repo's established
server-backed-interactive-app pattern (Gambit's play server, Formulate's
spreadsheet backend, Impulse's hand-rolled SSE physics stream).
"""
import json
import os
import queue
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

CLIENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'client')

# How long an SSE connection's blocking read waits before sending a
# keep-alive comment. Keeps intermediate proxies/browsers from deciding the
# connection is dead, and lets a subscriber thread notice a closed socket
# in bounded time instead of blocking forever.
HEARTBEAT_SECONDS = 15.0

STATIC_FILES = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/crdt.js': ('crdt.js', 'application/javascript; charset=utf-8'),
    '/net.js': ('net.js', 'application/javascript; charset=utf-8'),
    '/app.js': ('app.js', 'application/javascript; charset=utf-8'),
    '/style.css': ('style.css', 'text/css; charset=utf-8'),
}

DOC_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


class Document:
    """All server-side state for one collaborative document: an
    append-only op log (each entry gets a monotonically increasing `seq`
    so clients can resync with `?since=`) plus the set of currently
    connected subscriber queues to broadcast to."""

    def __init__(self):
        self.lock = threading.Lock()
        self.log = []  # list of {"seq": int, "op": <client op dict>}
        self.subscribers = set()  # set of queue.Queue

    def append_and_broadcast(self, op):
        with self.lock:
            seq = len(self.log) + 1
            entry = {'seq': seq, 'op': op}
            self.log.append(entry)
            subs = list(self.subscribers)
        for q in subs:
            q.put(('op', entry))
        return seq

    def broadcast_ephemeral(self, kind, payload):
        with self.lock:
            subs = list(self.subscribers)
        for q in subs:
            q.put((kind, payload))

    def backlog_since(self, since):
        with self.lock:
            return [e for e in self.log if e['seq'] > since]

    def subscribe(self):
        q = queue.Queue()
        with self.lock:
            self.subscribers.add(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.subscribers.discard(q)


class DocumentStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.docs = {}

    def get(self, doc_id):
        with self.lock:
            doc = self.docs.get(doc_id)
            if doc is None:
                doc = Document()
                self.docs[doc_id] = doc
            return doc


STORE = DocumentStore()


def valid_doc_id(doc_id):
    return bool(DOC_ID_RE.match(doc_id))


class Handler(BaseHTTPRequestHandler):
    server_version = 'Concord/1.0'
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        # Quiet by default; flip via CONCORD_VERBOSE=1 for debugging.
        if os.environ.get('CONCORD_VERBOSE'):
            sys.stderr.write('%s - - %s\n' % (self.address_string(), fmt % args))

    # ---- routing -----------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in STATIC_FILES:
            return self._serve_static(path)

        m = re.match(r'^/doc/([^/]+)/events$', path)
        if m:
            return self._handle_events(m.group(1), qs)

        m = re.match(r'^/doc/([^/]+)/snapshot$', path)
        if m:
            return self._handle_snapshot(m.group(1))

        self._send_json(404, {'error': 'not found'})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        m = re.match(r'^/doc/([^/]+)/ops$', path)
        if m:
            return self._handle_post_ops(m.group(1))

        m = re.match(r'^/doc/([^/]+)/cursor$', path)
        if m:
            return self._handle_post_cursor(m.group(1))

        self._send_json(404, {'error': 'not found'})

    # ---- static --------------------------------------------------------
    def _serve_static(self, path):
        filename, content_type = STATIC_FILES[path]
        full = os.path.join(CLIENT_DIR, filename)
        try:
            with open(full, 'rb') as f:
                body = f.read()
        except OSError:
            self._send_json(404, {'error': 'missing static file: %s' % filename})
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    # ---- API -------------------------------------------------------------
    def _handle_post_ops(self, doc_id):
        if not valid_doc_id(doc_id):
            return self._send_json(400, {'error': 'invalid doc id'})
        length = int(self.headers.get('Content-Length', '0') or '0')
        if length <= 0 or length > 10 * 1024 * 1024:
            return self._send_json(400, {'error': 'missing or oversized body'})
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return self._send_json(400, {'error': 'invalid JSON'})
        if not isinstance(payload, dict) or 'ops' not in payload or not isinstance(payload['ops'], list):
            return self._send_json(400, {'error': 'expected {"siteId": ..., "ops": [...]}'})
        site_id = payload.get('siteId', 'unknown')
        doc = STORE.get(doc_id)
        seqs = []
        for op in payload['ops']:
            if not isinstance(op, dict) or op.get('type') not in ('insert', 'delete'):
                return self._send_json(400, {'error': 'malformed op: %r' % (op,)})
            seqs.append(doc.append_and_broadcast({'siteId': site_id, 'op': op}))
        self._send_json(200, {'seqs': seqs})

    def _handle_post_cursor(self, doc_id):
        if not valid_doc_id(doc_id):
            return self._send_json(400, {'error': 'invalid doc id'})
        length = int(self.headers.get('Content-Length', '0') or '0')
        if length <= 0 or length > 64 * 1024:
            return self._send_json(400, {'error': 'missing or oversized body'})
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return self._send_json(400, {'error': 'invalid JSON'})
        if not isinstance(payload, dict) or 'siteId' not in payload:
            return self._send_json(400, {'error': 'expected {"siteId": ..., ...}'})
        doc = STORE.get(doc_id)
        doc.broadcast_ephemeral('cursor', payload)
        self._send_json(200, {'ok': True})

    def _handle_snapshot(self, doc_id):
        if not valid_doc_id(doc_id):
            return self._send_json(400, {'error': 'invalid doc id'})
        doc = STORE.get(doc_id)
        with doc.lock:
            log = list(doc.log)
        self._send_json(200, {'log': log})

    def _handle_events(self, doc_id, qs):
        if not valid_doc_id(doc_id):
            return self._send_json(400, {'error': 'invalid doc id'})
        try:
            since = int(qs.get('since', ['0'])[0])
        except ValueError:
            since = 0
        doc = STORE.get(doc_id)

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()

        backlog = doc.backlog_since(since)
        try:
            for entry in backlog:
                self._write_sse(self.wfile, 'op', entry)
            self._write_sse(self.wfile, 'ready', {'since': since, 'caughtUpTo': backlog[-1]['seq'] if backlog else since})
        except (BrokenPipeError, ConnectionResetError):
            return

        q = doc.subscribe()
        try:
            while True:
                try:
                    kind, payload = q.get(timeout=HEARTBEAT_SECONDS)
                except queue.Empty:
                    self.wfile.write(b': heartbeat\n\n')
                    self.wfile.flush()
                    continue
                self._write_sse(self.wfile, kind, payload)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            doc.unsubscribe(q)

    # ---- helpers -------------------------------------------------------
    def _write_sse(self, wfile, event, data):
        wfile.write(('event: %s\n' % event).encode('utf-8'))
        wfile.write(('data: %s\n\n' % json.dumps(data)).encode('utf-8'))
        wfile.flush()

    def _send_json(self, status, obj):
        body = json.dumps(obj).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(host='127.0.0.1', port=8420):
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    print('Concord relay listening on http://%s:%d' % (host, port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == '__main__':
    host = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8420
    serve(host, port)
