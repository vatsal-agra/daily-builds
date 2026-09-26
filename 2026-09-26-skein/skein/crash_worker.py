"""A worker process for `skein crash-demo`: opens the graph and commits
transactions of exactly `batch` nodes each, forever, until the parent
process kills it (SIGKILL) at an arbitrary point -- including mid-write of
a single transaction's WAL records. Run as `python -m skein.crash_worker
<path> <batch>`.
"""
import sys

from .storage import Graph


def main() -> None:
    path, batch = sys.argv[1], int(sys.argv[2])
    graph = Graph(path)
    while True:
        with graph.transaction():
            for _ in range(batch):
                graph.create_node(["Stress"], {})


if __name__ == "__main__":
    main()
