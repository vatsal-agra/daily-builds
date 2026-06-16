"""Live ASCII dashboard: animate a Raft cluster under chaos in the terminal.

Each frame shows, per node: its role, current term, a log bar (committed portion
filled, uncommitted hollow), commit index, and its partition group / liveness.
A header line tracks the leader, in-flight messages, and a rolling event feed of
injected faults. Rendering is separated from animation so the verification suite
can snapshot a single frame deterministically without sleeping.
"""

from __future__ import annotations

import random
import sys
import time

from .cluster import Cluster
from .raft import Config, Role
from .network import NetConfig
from .faults import random_partition

# ANSI
RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
RED = "\033[31m"; GREEN = "\033[32m"; YELLOW = "\033[33m"
BLUE = "\033[34m"; MAGENTA = "\033[35m"; CYAN = "\033[36m"; GREY = "\033[90m"
CLEAR = "\033[2J\033[H"; HOME = "\033[H"; HIDE = "\033[?25l"; SHOW = "\033[?25h"

ROLE_STYLE = {
    Role.LEADER: (GREEN + BOLD, "LEADER  "),
    Role.CANDIDATE: (YELLOW, "candidate"),
    Role.FOLLOWER: (CYAN, "follower"),
}
GROUP_COLORS = [BLUE, MAGENTA, YELLOW, GREEN, CYAN]


def _log_bar(node, width=40):
    """A bar of `width` cells representing the log; committed cells filled."""
    total = node.last_log_index()
    commit = node.commit_index
    if total <= 0:
        return DIM + "·" * width + RESET
    # Scale the log onto `width` cells.
    cells = []
    for c in range(width):
        idx = int(round((c + 1) / width * total))
        if idx == 0:
            cells.append(DIM + "·" + RESET)
        elif idx <= commit:
            cells.append(GREEN + "█" + RESET)
        else:
            cells.append(YELLOW + "▒" + RESET)
    return "".join(cells)


def _partition_groups(net, ids):
    """Return a node->group-index map for display (None if fully connected)."""
    if net._partitions is None:
        return {i: None for i in ids}
    out = {}
    for i in ids:
        out[i] = None
        for gi, g in enumerate(net._partitions):
            if i in g:
                out[i] = gi
                break
    return out


def render_frame(cluster: Cluster, events, width=40) -> str:
    ids = sorted(cluster.nodes)
    net = cluster.net
    groups = _partition_groups(net, ids)
    leader = cluster.leader()
    lines = []

    title = f"{BOLD}{CYAN}╔═ QUORUM · live Raft cluster ═══════════════════════════════════════╗{RESET}"
    lines.append(title)
    lead_txt = (f"{GREEN}node {leader} (term {cluster.nodes[leader].current_term}){RESET}"
                if leader is not None else f"{RED}— none —{RESET}")
    s = cluster.summary()
    lines.append(
        f"  t={cluster.time:<5d} leader={lead_txt}   "
        f"in-flight={net.in_flight():<3d} "
        f"{DIM}sent={net.sent} drop={net.dropped} dup={net.duplicated}{RESET}"
    )
    lines.append(
        f"  ops committed: {GREEN}{s['ops_committed']}{RESET}/{s['ops_total']}   "
        f"{DIM}(partition: "
        + ("none" if net._partitions is None
           else " | ".join("{" + ",".join(map(str, sorted(g))) + "}"
                            for g in net._partitions))
        + f"){RESET}"
    )
    lines.append(f"  {GREY}{'─'*68}{RESET}")
    lines.append(f"  {'node':<5}{'role':<11}{'term':>4}  {'log (commit=█ pending=▒)':<{width}}  cmt")

    for i in ids:
        n = cluster.nodes[i]
        alive = i in cluster.alive
        gi = groups[i]
        gcol = GROUP_COLORS[gi % len(GROUP_COLORS)] if gi is not None else ""
        if not alive:
            tag = f"{RED}✗ CRASHED{RESET}"
            rolecol, roletxt = DIM, "—"
            bar = DIM + "·" * width + RESET
        else:
            rolecol, roletxt = ROLE_STYLE[n.role]
            bar = _log_bar(n, width)
            tag = (f"{gcol}◧ grp{gi}{RESET}" if gi is not None else f"{GREEN}●{RESET}")
        marker = "★" if (alive and n.role == Role.LEADER) else " "
        lines.append(
            f"  {marker}{i:<4}{rolecol}{roletxt:<11}{RESET}{n.current_term:>4}  "
            f"{bar}  {n.commit_index:>3}  {tag}"
        )

    lines.append(f"  {GREY}{'─'*68}{RESET}")
    lines.append(f"  {BOLD}events{RESET}")
    feed = events[-5:] if events else []
    for ev in feed:
        lines.append(f"   {DIM}t={ev[0]:<5d}{RESET} {ev[1]}")
    for _ in range(5 - len(feed)):
        lines.append("")
    lines.append(f"{BOLD}{CYAN}╚════════════════════════════════════════════════════════════════════╝{RESET}")
    return "\n".join(lines)


def run_dashboard(seed=7, n=5, ticks=600, fps=12.0, chaos=True):
    rng = random.Random(seed ^ 0xDA5)
    cluster = Cluster(
        n=n, seed=seed,
        config=Config(election_min=8, election_max=16, heartbeat_interval=1),
        net_config=NetConfig(latency_min=1, latency_max=4,
                             loss_prob=0.04 if chaos else 0.0,
                             dup_prob=0.02 if chaos else 0.0),
        snapshot_threshold=30,
    )
    ids = list(range(n))
    events = []
    delay = 1.0 / max(fps, 1.0)
    interactive = sys.stdout.isatty()

    def log_event(msg):
        events.append((cluster.time, msg))

    try:
        if interactive:
            sys.stdout.write(HIDE + CLEAR)
        for t in range(1, ticks + 1):
            if t % 5 == 0:
                if rng.random() < 0.65:
                    cluster.client_request(("put", f"k{rng.randrange(4)}",
                                            rng.randrange(100)))
            if chaos and t % 22 == 0:
                roll = rng.random()
                live = sorted(cluster.alive)
                if roll < 0.3 and len(live) > n // 2 + 1:
                    v = rng.choice(live); cluster.crash(v)
                    log_event(f"{RED}crash node {v}{RESET}")
                elif roll < 0.5:
                    dead = [i for i in ids if i not in cluster.alive]
                    if dead:
                        v = rng.choice(dead); cluster.restart(v)
                        log_event(f"{GREEN}restart node {v}{RESET}")
                elif roll < 0.8:
                    cluster.partition(random_partition(rng, ids))
                    log_event(f"{YELLOW}partition the network{RESET}")
                else:
                    cluster.heal(); log_event(f"{CYAN}heal the network{RESET}")

            cluster.step()

            if t % max(1, int(round(1))) == 0:
                frame = render_frame(cluster, events)
                if interactive:
                    sys.stdout.write(HOME + frame + "\n")
                    sys.stdout.flush()
                    time.sleep(delay)
                elif t % 60 == 0:  # non-tty: emit periodic frames only
                    print(frame)
                    print()
        if not interactive:
            print(render_frame(cluster, events))
    finally:
        if interactive:
            sys.stdout.write(SHOW)
            sys.stdout.flush()
    # Settle and report.
    cluster.run_until_quiescent(max_ticks=400)
    print(f"\n{BOLD}Final:{RESET} leader=node {cluster.leader()}, "
          f"{cluster.summary()['ops_committed']}/{cluster.summary()['ops_total']} "
          f"ops committed, all replicas "
          f"{'agree' if len({tuple(sorted(cluster.kv_snapshot(i).items())) for i in cluster.alive})==1 else 'DIVERGED'}.")
