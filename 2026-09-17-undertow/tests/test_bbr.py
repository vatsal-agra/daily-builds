from src import experiments as exp
from src.congestion.bbr import BBR


def test_bbr_state_machine_starts_in_startup():
    cc = BBR()
    assert cc.mode == "STARTUP"


def test_bbr_bdp_estimate_needs_both_filters():
    cc = BBR()
    assert cc._bdp() == cc.cwnd  # no bandwidth/RTT samples yet -> falls back
    cc.bw_max = 100.0
    cc.min_rtt = 0.05
    assert abs(cc._bdp() - 5.0) < 1e-9


def test_single_flow_bbr_saturates_link_with_almost_no_loss():
    r = exp.run_single_flow(algo="bbr", duration_s=20, bandwidth_bps=2_000_000)
    utilization = r["flows"][0]["throughput_bps"] / 2_000_000
    assert utilization > 0.9
    assert r["drop_count"] <= 2, "BBR should rarely if ever need to drop a packet to find capacity"


def test_bbr_holds_a_shallower_queue_than_loss_based_algorithms_at_similar_utilization():
    r = exp.run_bbr_vs_loss_based(loss_algo="cubic", duration_s=30)
    bbr = r["results"]["bbr"]
    cubic = r["results"]["cubic"]
    assert bbr["utilization"] > 0.85
    assert cubic["utilization"] > 0.85
    assert bbr["mean_queue_packets"] < cubic["mean_queue_packets"] / 5, (
        f"expected BBR's mean queue ({bbr['mean_queue_packets']:.1f}) to be far "
        f"shallower than CUBIC's ({cubic['mean_queue_packets']:.1f}) at similar utilization"
    )
