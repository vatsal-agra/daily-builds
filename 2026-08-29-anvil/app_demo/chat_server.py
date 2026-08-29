#!/usr/bin/env python3
"""Anvil's flagship demo: a live WebSocket chat room, served entirely by
Anvil itself -- static HTML/CSS/JS over HTTP (with real Range/conditional
GET support you can prove with curl), and the chat protocol over a real
RFC 6455 WebSocket connection. Zero other web framework involved.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anvil import Router, Server, Response  # noqa: E402

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

router = Router()
router.mount_static("/static", STATIC_DIR)

_rooms = {}  # room name -> set of WSConnection wrappers
_names = {}  # WSConnection -> display name
_start_time = time.monotonic()
_stats = {"messages": 0, "connections": 0}


@router.route("GET", "/")
def index(req):
    return Response(302, headers=[("Location", "/static/index.html")])


@router.route("GET", "/api/status")
def status(req):
    return Response.json({
        "uptime_seconds": round(time.monotonic() - _start_time, 1),
        "rooms": {name: len(members) for name, members in _rooms.items()},
        "total_connections": _stats["connections"],
        "total_messages": _stats["messages"],
    })


@router.route("GET", "/api/echo/{word}")
def echo(req):
    # a tiny required-route-param demo endpoint, also handy for curl tests
    return Response.json({"word": req.params["word"], "query": req.query})


class ChatRoom:
    """One instance per WebSocket connection; `req.params['room']` names
    which broadcast group it joins."""

    def __init__(self, req):
        self.room = req.params.get("room", "lobby") or "lobby"
        self.name = None

    def on_open(self, conn):
        _rooms.setdefault(self.room, set()).add(conn)
        _stats["connections"] += 1
        conn.send_text(json.dumps({"type": "welcome", "room": self.room,
                                    "members": len(_rooms[self.room])}))

    def on_message(self, conn, payload, kind):
        if kind != "text":
            return  # binary frames are accepted by the protocol but unused here
        try:
            msg = json.loads(payload)
        except ValueError:
            conn.send_text(json.dumps({"type": "error", "error": "invalid JSON"}))
            return
        mtype = msg.get("type")
        if mtype == "join":
            name = str(msg.get("name", "anon"))[:32].strip() or "anon"
            self.name = name
            _names[conn] = name
            self._broadcast({"type": "system", "text": f"{name} joined {self.room}"})
        elif mtype == "chat":
            if self.name is None:
                conn.send_text(json.dumps({"type": "error", "error": "join first"}))
                return
            text = str(msg.get("text", ""))[:2000].strip()
            if not text:
                return  # nothing to broadcast; silently drop rather than send an empty bubble
            _stats["messages"] += 1
            self._broadcast({"type": "chat", "from": self.name, "text": text,
                              "ts": time.time()})
        else:
            conn.send_text(json.dumps({"type": "error", "error": f"unknown type {mtype!r}"}))

    def on_close(self, conn, code, reason):
        members = _rooms.get(self.room)
        if members and conn in members:
            members.discard(conn)
        name = _names.pop(conn, None)
        if name:
            self._broadcast({"type": "system", "text": f"{name} left {self.room}"})

    def _broadcast(self, obj):
        payload = json.dumps(obj)
        for member in list(_rooms.get(self.room, ())):
            member.send_text(payload)


router.add_ws_route("/ws/{room}", ChatRoom)
router.add_ws_route("/ws", ChatRoom)


def main():
    ap = argparse.ArgumentParser(description="Anvil chat demo server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    if not (0 <= args.port <= 65535):
        print(f"error: --port must be 0-65535, got {args.port}", file=sys.stderr)
        raise SystemExit(1)

    server = Server(host=args.host, port=args.port, router=router)
    try:
        server.bind()
    except OSError as e:
        print(f"error: couldn't bind {args.host}:{args.port} -- {e}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Anvil chat demo listening on http://{args.host}:{server.port}/")
    print(f"  -> open http://{args.host}:{server.port}/ in a browser")
    print(f"  -> WebSocket endpoint: ws://{args.host}:{server.port}/ws/<room>")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
