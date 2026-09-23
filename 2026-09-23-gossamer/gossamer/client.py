"""Thin client helpers: a "client" in Gossamer is just any HTTP caller
hitting any node's /kv/<key> endpoint -- that node becomes the coordinator
for this one request. There is nothing special about which node is asked.
"""
from urllib.parse import quote

from . import httpjson


def put(cluster, coordinator_node_id, key, value, context=None, timeout=3.0):
    host, port = cluster.address_of(coordinator_node_id)
    status, body = httpjson.post_json(
        host, port, f"/kv/{quote(key, safe='')}", {"value": value, "context": context},
        timeout=timeout,
    )
    return status, body


def get(cluster, coordinator_node_id, key, timeout=3.0):
    host, port = cluster.address_of(coordinator_node_id)
    status, body = httpjson.get_json(host, port, f"/kv/{quote(key, safe='')}", timeout=timeout)
    return status, body
