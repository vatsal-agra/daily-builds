"""The FAT16 File Allocation Table itself: a flat array of 16-bit entries
that forms an on-disk singly-linked list per file — entry N holds either 0
(free), the next cluster in the chain, an end-of-chain marker (>=0xFFF8), or
a bad-cluster marker (0xFFF7). Clusters 0 and 1 are reserved and never part
of a file's chain.
"""
import struct

FREE = 0x0000
BAD = 0xFFF7
EOC = 0xFFFF          # value this toolkit *writes* to terminate a chain
EOC_MIN = 0xFFF8       # any value >= this read back means "end of chain"


class FatFullError(RuntimeError):
    """Not enough free clusters to satisfy an allocation request."""


class Fat:
    """One FAT table's worth of 16-bit entries, kept as a Python list of ints
    in memory. `Image` is responsible for writing this out to *both* on-disk
    FAT copies (FAT16 volumes keep num_fats identical mirrors)."""

    def __init__(self, entries):
        self.entries = entries  # list[int], index 0..count_of_clusters+1

    @classmethod
    def new(cls, count_of_clusters, media):
        # Entries for cluster 0 and 1 are reserved housekeeping slots, not
        # real clusters; data clusters run from index 2 up to count+1.
        n = count_of_clusters + 2
        entries = [FREE] * n
        entries[0] = 0xFF00 | media
        entries[1] = 0xFFFF  # high bits here record clean-shutdown status; we always say clean
        return cls(entries)

    @classmethod
    def from_bytes(cls, raw, count_of_clusters):
        """Parse a FAT region and keep only the entries that correspond to
        real clusters (indices 0..count_of_clusters+1). A FAT region is
        sized in whole sectors, so it is almost always padded with trailing
        zero bytes past the last real cluster — those padding "entries"
        read as FREE but are not real clusters and must never be handed out
        by allocate(), or the allocator would compute offsets past the data
        region."""
        n = count_of_clusters + 2
        needed_bytes = n * 2
        if len(raw) < needed_bytes:
            raise ValueError(
                f"FAT region is {len(raw)} bytes, too small for "
                f"{count_of_clusters} clusters ({needed_bytes} bytes needed)"
            )
        entries = list(struct.unpack(f"<{n}H", raw[:needed_bytes]))
        return cls(entries)

    def to_bytes(self, byte_size):
        raw = struct.pack(f"<{len(self.entries)}H", *self.entries)
        if len(raw) < byte_size:
            raw += bytes(byte_size - len(raw))
        return raw[:byte_size]

    def __len__(self):
        return len(self.entries) - 2  # usable data-cluster count

    def get(self, cluster):
        return self.entries[cluster]

    def set(self, cluster, value):
        self.entries[cluster] = value

    def is_free(self, cluster):
        return self.entries[cluster] == FREE

    def is_eoc(self, value):
        return value >= EOC_MIN

    def chain(self, start_cluster):
        """Follow a chain starting at `start_cluster`, returning the list of
        cluster numbers in order. Raises on a corrupt/cyclic chain instead of
        looping forever."""
        if start_cluster < 2:
            return []
        out = []
        seen = set()
        cur = start_cluster
        while True:
            if cur in seen:
                raise ValueError(f"cyclic FAT chain detected at cluster {cur}")
            seen.add(cur)
            out.append(cur)
            nxt = self.entries[cur]
            if nxt == FREE:
                raise ValueError(f"chain broken: cluster {cur} points at free cluster 0 — corrupt FAT")
            if nxt == BAD:
                raise ValueError(f"chain references bad-cluster marker after cluster {cur}")
            if self.is_eoc(nxt):
                break
            cur = nxt
        return out

    def _free_clusters(self):
        for c in range(2, len(self.entries)):
            if self.entries[c] == FREE:
                yield c

    def count_free(self):
        return sum(1 for c in range(2, len(self.entries)) if self.entries[c] == FREE)

    def allocate(self, n_clusters):
        """Allocate a chain of exactly n_clusters free clusters, link them in
        the table, terminate with EOC, and return the list of cluster numbers
        in chain order. Raises FatFullError if there isn't room."""
        if n_clusters <= 0:
            raise ValueError("n_clusters must be positive")
        free = []
        for c in self._free_clusters():
            free.append(c)
            if len(free) == n_clusters:
                break
        if len(free) < n_clusters:
            raise FatFullError(
                f"requested {n_clusters} clusters but only {len(free)} are free"
            )
        for i, c in enumerate(free):
            self.entries[c] = free[i + 1] if i + 1 < len(free) else EOC
        return free

    def extend(self, start_cluster, n_more):
        """Grow an existing chain by n_more clusters, relinking the old tail's
        EOC to the new clusters. Returns the newly allocated cluster numbers."""
        existing = self.chain(start_cluster)
        tail = existing[-1]
        new_clusters = self.allocate(n_more)
        self.entries[tail] = new_clusters[0]
        return new_clusters

    def free_chain(self, start_cluster):
        """Mark every cluster in a chain free again."""
        if start_cluster < 2:
            return
        for c in self.chain(start_cluster):
            self.entries[c] = FREE
