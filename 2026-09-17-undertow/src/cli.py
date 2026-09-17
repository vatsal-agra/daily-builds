"""Command-line entry point: run one experiment, print a human-readable
summary, and optionally export the full time-series result as JSON for the
HTML visualizer."""

from __future__ import annotations

import argparse
import json
import sys

from . import experiments as exp


def _strip_private(obj):
    if isinstance(obj, dict):
        return {k: _strip_private(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [_strip_private(v) for v in obj]
    return obj


SCENARIOS = {
    "single": lambda a: exp.run_single_flow(algo=a.algo, duration_s=a.duration),
    "fairness": lambda a: exp.run_fairness_same_rtt(algo=a.algo, n_flows=a.flows, duration_s=a.duration),
    "rtt-unfairness": lambda a: exp.run_rtt_unfairness(algo=a.algo, duration_s=a.duration),
    "bufferbloat": lambda a: exp.run_bufferbloat(algo=a.algo, use_red=a.red, duration_s=a.duration),
    "bbr-vs-loss": lambda a: exp.run_bbr_vs_loss_based(loss_algo=a.algo, duration_s=a.duration),
}


def _print_summary(scenario, result) -> None:
    print(f"=== {scenario} ===")
    if scenario == "single":
        f = result["flows"][0]
        print(f"algorithm={f['algorithm']} delivered={f['delivered_segments']} "
              f"throughput={f['throughput_bps'] / 1e6:.3f} Mbps drops={result['drop_count']}")
    elif scenario == "fairness":
        for f in result["flows"]:
            print(f"{f['name']}: throughput={f['throughput_bps'] / 1e6:.3f} Mbps "
                  f"delivered={f['delivered_segments']}")
        print(f"final Jain's fairness index (last interval) = {result['final_fairness']:.4f}")
    elif scenario == "rtt-unfairness":
        print(f"RTT ratio (long/short) = {result['rtt_ratio_long_over_short']:.2f}")
        s = result["steady_throughput_bps"]
        print(f"steady-state throughput (trial 1): short-RTT={s['short_rtt'] / 1e6:.3f} Mbps, "
              f"long-RTT={s['long_rtt'] / 1e6:.3f} Mbps")
        print(f"throughput ratio (short/long), trial 1 = {result['throughput_ratio_short_over_long']:.2f}")
        print(f"pooled throughput ratio over {result['n_trials']} trials = "
              f"{result['pooled_throughput_ratio_short_over_long']:.2f}")
    elif scenario == "bufferbloat":
        print(f"RED={'on' if result['use_red'] else 'off'} base_rtt={result['base_rtt_s'] * 1000:.1f}ms "
              f"mean_ping_rtt={result['mean_ping_rtt_s'] * 1000:.1f}ms "
              f"max_ping_rtt={result['max_ping_rtt_s'] * 1000:.1f}ms "
              f"bloat_ratio={result['bloat_ratio']:.2f}x "
              f"utilization={result['bottleneck_utilization'] * 100:.1f}%")
    elif scenario == "bbr-vs-loss":
        for algo, r in result["results"].items():
            print(f"{algo}: utilization={r['utilization'] * 100:.1f}% "
                  f"mean_queue={r['mean_queue_packets']:.1f} packets")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="undertow", description="From-scratch TCP congestion-control simulator")
    p.add_argument("scenario", choices=sorted(SCENARIOS))
    p.add_argument("--algo", default="reno", choices=["reno", "cubic", "bbr"])
    p.add_argument("--duration", type=float, default=30.0)
    p.add_argument("--flows", type=int, default=2)
    p.add_argument("--red", action="store_true", help="use RED instead of drop-tail (bufferbloat scenario)")
    p.add_argument("--out", type=str, default=None, help="write full JSON result to this path")
    args = p.parse_args(argv)

    result = SCENARIOS[args.scenario](args)
    _print_summary(args.scenario, result)
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(_strip_private(result), fh, indent=2)
        print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
