"""Tiny stdlib-only JSON-over-HTTP helper for node-to-node RPC."""
import http.client
import json
import socket


class NodeUnreachable(Exception):
    pass


def request(method, host, port, path, payload=None, timeout=2.0):
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        body = json.dumps(payload).encode("utf-8") if payload is not None else b""
        headers = {"Content-Type": "application/json"}
        try:
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except (ConnectionRefusedError, socket.timeout, OSError, http.client.HTTPException) as e:
            raise NodeUnreachable(f"{host}:{port} {path}: {e}") from e
        status = resp.status
        if data:
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                parsed = {"raw": data.decode("utf-8", errors="replace")}
        else:
            parsed = {}
        return status, parsed
    finally:
        conn.close()


def get_json(host, port, path, timeout=2.0):
    return request("GET", host, port, path, None, timeout)


def post_json(host, port, path, payload, timeout=2.0):
    return request("POST", host, port, path, payload, timeout)
