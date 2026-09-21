"""Checkpoint (de)serialization for PolicyValueNet, using plain .npz --
no pickle of arbitrary Python objects, just named arrays."""

from __future__ import annotations
import numpy as np
from .nn.network import PolicyValueNet


def save_checkpoint(net: PolicyValueNet, path: str):
    state = net.get_state()
    np.savez(path, **state)


def load_checkpoint(path: str) -> PolicyValueNet:
    data = np.load(path)
    hidden_sizes = tuple(int(v) for v in data["_hidden_sizes"])
    input_dim = int(data["_input_dim"][0])
    action_size = int(data["_action_size"][0])
    net = PolicyValueNet(input_dim, action_size, hidden_sizes=hidden_sizes, seed=0)
    net.set_state({k: data[k] for k in data.files})
    return net
