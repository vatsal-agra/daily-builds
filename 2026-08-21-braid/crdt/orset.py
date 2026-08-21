"""OR-Set — Observed-Remove Set, add-wins semantics.

A naive replicated set (just union adds, union removes) has a well-known
bug: if peer A adds "x" and peer B concurrently removes "x" (an element
B never actually saw added, or saw and is racing to remove), the result
depends on delivery order — sometimes "x" ends up in the set, sometimes
not. That's not a CRDT, it's a coin flip.

OR-Set fixes this by tagging every individual `add` with a fresh unique
id. `remove(value)` doesn't remove the *value* — it removes the
*specific tags this peer has currently observed* for that value. A
concurrent add (a tag the remover never saw, because it hadn't been
delivered yet) survives, because its tag was never in the removed set.
This is "add-wins": in a race between concurrent add and remove of the
same value, add always wins convergence, which is the behavior most
applications actually want (an item concurrently re-added while being
removed elsewhere should end up present, not silently dropped).

State-based, like `PNCounter` — merge is union of `added` tags per value
and union of all `removed` tags, both monotonically growing sets, so
merge is a trivial, correct join.
"""

from __future__ import annotations


class ORSet:
    def __init__(self, peer_id: str):
        self.peer_id = peer_id
        self._counter = 0
        self._added: dict = {}  # value -> set of (peer_id, counter) tags
        self._removed: set = set()  # tags that have been removed

    def add(self, value) -> None:
        self._counter += 1
        tag = (self.peer_id, self._counter)
        self._added.setdefault(value, set()).add(tag)

    def remove(self, value) -> None:
        """Removes every tag *this peer currently knows about* for
        `value`. A tag added concurrently elsewhere, not yet observed
        here, is untouched — that's the add-wins guarantee."""
        for tag in self._added.get(value, set()):
            self._removed.add(tag)

    def contains(self, value) -> bool:
        live = self._added.get(value, set()) - self._removed
        return len(live) > 0

    def values(self) -> set:
        return {v for v, tags in self._added.items() if tags - self._removed}

    def state(self) -> dict:
        return {
            "added": {v: set(tags) for v, tags in self._added.items()},
            "removed": set(self._removed),
        }

    def merge(self, other_state: dict) -> None:
        for value, tags in other_state.get("added", {}).items():
            self._added.setdefault(value, set()).update(tags)
        self._removed.update(other_state.get("removed", set()))

    def __repr__(self):
        return f"ORSet({sorted(self.values(), key=str)!r})"
