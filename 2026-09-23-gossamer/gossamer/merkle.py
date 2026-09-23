"""Merkle tree over a node's key space, for anti-entropy diffing.

Real Dynamo builds one Merkle tree per (key-range, replica-pair) so two
replicas can diff their trees and exchange only the actually-divergent
leaves instead of a full resync. This is a simplified but genuine version
of the same idea: the keyspace is hashed into a fixed number of buckets
(instead of the exact key ranges a real ring partition owns), each bucket's
leaf hash summarizes every key+value+vclock that falls in it, and two
nodes only need to walk the *differing* bucket ids to find what to repair.
"""
import hashlib

KEY_RANGE_BUCKETS = 64


def _bucket_for(key, buckets):
    return str(int(hashlib.sha1(key.encode("utf-8")).hexdigest(), 16) % buckets)


class BuiltTree:
    def __init__(self, bucket_keys, bucket_hashes):
        self._bucket_keys = bucket_keys
        self._bucket_hashes = bucket_hashes

    def leaf_hashes(self):
        return dict(self._bucket_hashes)

    def keys_in_bucket(self, bucket_id):
        return list(self._bucket_keys.get(bucket_id, []))

    def diff(self, other_hashes):
        """Bucket ids whose hash differs (or is missing) on either side."""
        all_buckets = set(self._bucket_hashes) | set(other_hashes)
        return [b for b in all_buckets if self._bucket_hashes.get(b) != other_hashes.get(b)]


class MerkleTree:
    def __init__(self, buckets=KEY_RANGE_BUCKETS):
        self.buckets = buckets

    def build(self, data_snapshot):
        """data_snapshot: dict key -> list[(value, VectorClock, ts)]."""
        bucket_keys = {}
        for key in data_snapshot:
            bucket_keys.setdefault(_bucket_for(key, self.buckets), []).append(key)

        bucket_hashes = {}
        for bucket_id, keys in bucket_keys.items():
            h = hashlib.sha1()
            for key in sorted(keys):
                siblings = data_snapshot[key]
                sib_repr = "|".join(
                    sorted(f"{v!r}:{sorted(vc.to_dict().items())}" for v, vc, _ts in siblings)
                )
                h.update(f"{key}={sib_repr};".encode("utf-8"))
            bucket_hashes[bucket_id] = h.hexdigest()
        return BuiltTree(bucket_keys, bucket_hashes)
