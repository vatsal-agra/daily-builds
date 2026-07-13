"""Default host-import environment Kiln offers to modules it runs: a
minimal `env.print` (used by Pebble's `print` statement) plus a WASI-lite
`wasi_snapshot_preview1.fd_write`, just enough of the real WASI ABI for a
module to print a byte buffer to stdout/stderr without any other WASI
machinery. Both are genuine WASM imports — the module calls into Python
through the normal import-linking path, not a shortcut."""

import sys

from .wasm.interpreter import HostFunc

I32 = 0x7F


def _print_i32(x):
    print(x)
    return []


def make_fd_write(get_memory):
    """WASI's fd_write(fd, iovs_ptr, iovs_len, nwritten_ptr) -> errno.
    `iovs` is an array of (buf_ptr: i32, buf_len: i32) pairs in linear
    memory. We support stdout (fd=1) and stderr (fd=2); anything else
    returns EBADF (8), matching the real WASI error code."""

    def fd_write(fd, iovs_ptr, iovs_len, nwritten_ptr):
        memory = get_memory()
        if fd not in (1, 2):
            return [8]
        stream = sys.stdout if fd == 1 else sys.stderr
        total = 0
        for i in range(iovs_len):
            base = iovs_ptr + i * 8
            buf_ptr = int.from_bytes(memory[base:base + 4], "little")
            buf_len = int.from_bytes(memory[base + 4:base + 8], "little")
            data = bytes(memory[buf_ptr:buf_ptr + buf_len])
            stream.write(data.decode("utf-8", errors="replace"))
            total += buf_len
        memory[nwritten_ptr:nwritten_ptr + 4] = total.to_bytes(4, "little")
        return [0]

    return fd_write


def default_imports(instance_holder=None):
    """Returns the standard import environment. `instance_holder` is a
    one-element list the caller fills with the Instance after construction
    (fd_write needs live access to the module's own memory, which doesn't
    exist yet at import-build time — a normal chicken-and-egg in any WASM
    embedder, solved the same way real ones do: a lazy memory getter)."""
    holder = instance_holder if instance_holder is not None else []

    def get_memory():
        return holder[0].memory

    return {
        "env": {
            "print": HostFunc(_print_i32, [I32], []),
        },
        "wasi_snapshot_preview1": {
            "fd_write": HostFunc(make_fd_write(get_memory), [I32, I32, I32, I32], [I32]),
        },
    }, holder
