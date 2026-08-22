"""Run a query in a dedicated thread with a large OS stack and a raised
Python recursion limit.

solve() is a plain recursive generator: each nested predicate call, cut
barrier, and conjunction step is a few more Python stack frames. Horn has
no tail-call optimization (neither does real Prolog, without an explicit
last-call-optimization compiler pass), so a program doing deep non-tail
recursion -- e.g. length/2 walking a several-hundred-element list -- can
run out of stack.

The naive fix, `sys.setrecursionlimit(a much bigger number)`, is actually
dangerous on its own: Python's recursion limit only guards against
exhausting the *interpreter's* notion of depth, not the underlying OS
thread stack. Measured during this project's own build: raising the limit
to 20000 on the default (8 MiB) thread stack doesn't raise a clean
RecursionError -- it segfaults the whole process around 5000 nested calls,
because the C stack itself runs out first. Running the search in a thread
created with a much larger stack fixes this for real: recursion then either
completes or fails cleanly with RecursionError, never a segfault. Measured
safe to roughly 10,000 nested Horn calls with these settings (a several-
thousand-element list via length/2); comfortably past anything the shipped
examples or stdlib predicates need.
"""

import sys
import threading

STACK_SIZE = 256 * 1024 * 1024  # 256 MiB
RECURSION_LIMIT = 60000


def run_with_stack(fn, *args, **kwargs):
    """Run fn(*args, **kwargs) to completion in a worker thread with a large
    stack and a raised recursion limit, then return its result (or re-raise
    whatever it raised) in the calling thread."""
    box = {}

    def target():
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(RECURSION_LIMIT)
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001 - deliberately re-raised below
            box["error"] = e
        finally:
            sys.setrecursionlimit(old_limit)

    old_stack_size = threading.stack_size()
    threading.stack_size(STACK_SIZE)
    try:
        t = threading.Thread(target=target)
        t.start()
        t.join()
    finally:
        threading.stack_size(old_stack_size)
    if "error" in box:
        raise box["error"]
    return box.get("value")
