import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.setrecursionlimit(100000)

from lemma.session import Session  # noqa: E402

_prelude_cache = {}


def fresh_session():
    return Session()


_base = None


def clone_session():
    """A fresh session with the prelude already loaded (deep copy of a cached one — 3x faster)."""
    global _base
    import copy
    if _base is None:
        _base = Session()
    return copy.deepcopy(_base)


def run(src, sess=None):
    """Run source in a fresh session; return (session, errors-as-one-string)."""
    s = sess or clone_session()
    s.out.clear()
    n0 = len(s.errors)
    s.run(src, "test.lm")
    return s, "\n".join(s.errors[n0:])


def ok(src):
    s, err = run(src)
    assert not err, err
    return s


def big_stack(fn, *a):
    sys.setrecursionlimit(200000)
    threading.stack_size(256 * 1024 * 1024)
    box = []
    t = threading.Thread(target=lambda: box.append(fn(*a)))
    t.start(); t.join()
    threading.stack_size(0)
    return box[0] if box else None
