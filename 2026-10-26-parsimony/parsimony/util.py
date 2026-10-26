"""Helpers shared across modules."""
import gc
import sys
import threading


def run_deep(fn, *args, stack_mb: int = 512, limit: int = 1_000_000):
    """Run ``fn`` on a thread with a big C stack and a high recursion limit.

    Forest walking and JSON encoding recurse once per tree level, and left-recursive lists
    make trees as deep as the input is long; the default 1000-frame limit would reject
    perfectly valid inputs of a few thousand tokens.
    """
    box = {}

    def target():
        try:
            box["value"] = fn(*args)
        except BaseException as e:           # re-raised on the caller's thread
            box["error"] = e

    old_limit, old_stack, gc_was = sys.getrecursionlimit(), threading.stack_size(), gc.isenabled()
    gc.disable()          # cyclic GC rescans the whole deep structure on every pass → quadratic
    sys.setrecursionlimit(limit)
    threading.stack_size(stack_mb * 1024 * 1024)
    try:
        t = threading.Thread(target=target)
        t.start(); t.join()
    finally:
        sys.setrecursionlimit(old_limit)
        threading.stack_size(old_stack)
        if gc_was:
            gc.enable()
    if "error" in box:
        raise box["error"]
    return box["value"]
