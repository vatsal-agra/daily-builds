import hashlib
import os
import shutil
import struct
import tempfile
import threading
import unittest

from conduit.api import Listener, connect
from tools.conduit_cp import recv_file, run_local_demo, send_file


class TestConduitCp(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.src_dir = os.path.join(self.tmpdir, "src")
        self.dst_dir = os.path.join(self.tmpdir, "dst")
        os.makedirs(self.src_dir)
        os.makedirs(self.dst_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_src(self, name, content: bytes):
        path = os.path.join(self.src_dir, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_clean_network_roundtrip(self):
        content = os.urandom(200_000)
        path = self._write_src("payload.bin", content)

        listener = Listener(("127.0.0.1", 0))
        result = {}

        def receiver():
            conn = listener.accept(timeout=5.0)
            try:
                result["recv"] = recv_file(conn, self.dst_dir)
            finally:
                conn.close()

        t = threading.Thread(target=receiver)
        t.start()
        conn = connect(listener.local_addr, timeout=5.0)
        try:
            sent_size, sent_digest = send_file(conn, path)
        finally:
            conn.close()
        t.join(timeout=10)
        listener.close()

        out_path, recv_size, recv_digest = result["recv"]
        self.assertEqual(sent_size, recv_size)
        self.assertEqual(sent_digest, recv_digest)
        self.assertEqual(hashlib.sha256(content).hexdigest(), recv_digest)
        with open(out_path, "rb") as f:
            self.assertEqual(f.read(), content)

    def test_lossy_demo_delivers_exact_file(self):
        content = os.urandom(150_000)
        path = self._write_src("chaos.bin", content)
        result = run_local_demo(
            path, self.dst_dir, loss=0.07, dup_prob=0.02, reorder_prob=0.06, seed=123,
        )
        send_size, send_digest = result["send"]
        recv_path, recv_size, recv_digest = result["recv"]
        self.assertEqual(send_size, recv_size)
        self.assertEqual(send_digest, recv_digest)
        self.assertGreater(result["netsim_stats"]["dropped"], 0)
        with open(recv_path, "rb") as f:
            self.assertEqual(f.read(), content)

    def test_empty_file(self):
        path = self._write_src("empty.bin", b"")
        listener = Listener(("127.0.0.1", 0))
        result = {}

        def receiver():
            conn = listener.accept(timeout=5.0)
            try:
                result["recv"] = recv_file(conn, self.dst_dir)
            finally:
                conn.close()

        t = threading.Thread(target=receiver)
        t.start()
        conn = connect(listener.local_addr, timeout=5.0)
        try:
            send_file(conn, path)
        finally:
            conn.close()
        t.join(timeout=10)
        listener.close()

        out_path, size, digest = result["recv"]
        self.assertEqual(size, 0)
        self.assertEqual(digest, hashlib.sha256(b"").hexdigest())

    def test_malicious_filename_cannot_escape_out_dir(self):
        # Craft a wire payload by hand with a path-traversal filename —
        # recv_file must never write outside out_dir.
        listener = Listener(("127.0.0.1", 0))
        result = {}

        def receiver():
            conn = listener.accept(timeout=5.0)
            try:
                result["recv"] = recv_file(conn, self.dst_dir)
            finally:
                conn.close()

        t = threading.Thread(target=receiver)
        t.start()
        conn = connect(listener.local_addr, timeout=5.0)
        try:
            evil_name = "../../etc/evil.txt".encode("utf-8")
            content = b"malicious content"
            conn.sendall(struct.pack("!Q", len(evil_name)) + evil_name)
            conn.sendall(struct.pack("!Q", len(content)) + content)
            conn.sendall(hashlib.sha256(content).digest())
        finally:
            conn.close()
        t.join(timeout=10)
        listener.close()

        out_path, size, digest = result["recv"]
        # basename() strips the traversal — the file must land inside dst_dir.
        self.assertTrue(os.path.realpath(out_path).startswith(os.path.realpath(self.dst_dir)))
        self.assertTrue(os.path.exists(out_path))

    def test_corrupted_checksum_is_detected(self):
        listener = Listener(("127.0.0.1", 0))
        result = {}
        error = {}

        def receiver():
            conn = listener.accept(timeout=5.0)
            try:
                result["recv"] = recv_file(conn, self.dst_dir)
            except ValueError as e:
                error["err"] = e
            finally:
                conn.close()

        t = threading.Thread(target=receiver)
        t.start()
        conn = connect(listener.local_addr, timeout=5.0)
        try:
            name = b"x.bin"
            content = b"some real content"
            conn.sendall(struct.pack("!Q", len(name)) + name)
            conn.sendall(struct.pack("!Q", len(content)) + content)
            conn.sendall(b"\x00" * 32)  # deliberately wrong digest
        finally:
            conn.close()
        t.join(timeout=10)
        listener.close()

        self.assertIn("err", error)
        self.assertIn("checksum mismatch", str(error["err"]))


if __name__ == "__main__":
    unittest.main()
