"""A durable, checksummed, append-only event log -- the write-ahead journal
that makes crash recovery possible.

The contract: every event that will mutate engine state is appended to the
journal (flushed + fsynced) *before* the engine applies it in memory. If the
process dies at any point, replaying the journal from an empty engine
reproduces exactly the state that was live a moment before the crash --
nothing more, nothing less, because nothing is ever considered "done" until
it is durably on disk.

Format: one JSON object per line, prefixed with its own CRC-32 (over the
exact JSON bytes that follow) so a torn write at the very end of the file
(the only place a real crash can land mid-record) is detected and the
truncated last line is dropped rather than silently misread as valid.
"""
from __future__ import annotations

import json
import os
import zlib
from dataclasses import dataclass


class JournalCorruption(Exception):
    """A journal line's CRC didn't match its payload."""


@dataclass
class JournalEntry:
    line_no: int
    event: dict


class Journal:
    def __init__(self, path: str, truncate: bool = False):
        self.path = path
        mode = "w" if truncate else "a"
        # Create the file if missing, and always reopen in append mode for
        # subsequent writes regardless of the initial mode.
        with open(path, mode, encoding="utf-8"):
            pass
        self._fh = open(path, "a", encoding="utf-8")

    def append(self, event: dict) -> None:
        payload = json.dumps(event, sort_keys=True, separators=(",", ":"))
        crc = zlib.crc32(payload.encode("utf-8"))
        self._fh.write(f"{crc:08x} {payload}\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "Journal":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @staticmethod
    def read_all(path: str, strict: bool = True) -> list[dict]:
        """Read every valid event from `path` in order.

        A line whose CRC does not match its payload is, by default
        (`strict=True`), treated as a torn/incomplete final write and
        silently truncated from the replay -- exactly what a real crash
        mid-`write()` looks like. Pass `strict=False` to instead raise
        `JournalCorruption`, e.g. when checking a log that should never have
        been touched after the fact.
        """
        events: list[dict] = []
        if not os.path.exists(path):
            return events
        with open(path, "r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.rstrip("\n")
                if not line:
                    continue
                try:
                    crc_hex, payload = line.split(" ", 1)
                    expected = int(crc_hex, 16)
                except ValueError:
                    if strict:
                        break
                    raise JournalCorruption(f"malformed journal line {line_no}: {line!r}")
                actual = zlib.crc32(payload.encode("utf-8"))
                if actual != expected:
                    if strict:
                        # Torn write (or genuine corruption) at/near EOF:
                        # stop replay here, exactly like a real crash would.
                        break
                    raise JournalCorruption(
                        f"CRC mismatch on journal line {line_no}: "
                        f"expected {expected:08x}, got {actual:08x}"
                    )
                events.append(json.loads(payload))
        return events
