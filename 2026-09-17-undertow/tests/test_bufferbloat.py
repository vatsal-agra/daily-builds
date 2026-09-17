from src import experiments as exp


def test_drop_tail_deep_queue_causes_bufferbloat():
    r = exp.run_bufferbloat(algo="reno", use_red=False, duration_s=30)
    assert r["bottleneck_utilization"] > 0.9
    assert r["bloat_ratio"] > 5.0, (
        f"expected the ping flow's RTT to balloon to several times the base "
        f"RTT under a bulk flow on a deep drop-tail queue, got {r['bloat_ratio']:.1f}x"
    )


def test_red_reduces_bufferbloat_without_killing_utilization():
    drop_tail = exp.run_bufferbloat(algo="reno", use_red=False, duration_s=30)
    red = exp.run_bufferbloat(algo="reno", use_red=True, duration_s=30)
    assert red["bloat_ratio"] < drop_tail["bloat_ratio"] * 0.7, (
        f"expected RED ({red['bloat_ratio']:.1f}x) to meaningfully reduce "
        f"queueing delay versus drop-tail ({drop_tail['bloat_ratio']:.1f}x)"
    )
    assert red["bottleneck_utilization"] > 0.7, "RED should not tank throughput to get there"
