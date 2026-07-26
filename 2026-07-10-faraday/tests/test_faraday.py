import json
import math
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from faraday import ac, circuits, dc, netlist, transient
from faraday.elements import Capacitor, Diode, Inductor, ISource, OpAmp, Resistor, VSource
from faraday.linalg import SingularMatrixError, solve
from faraday.mna import Circuit
from faraday.server import Handler


def close(a, b, rel=1e-6, abs_tol=1e-9):
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


class LinalgTests(unittest.TestCase):
    def test_2x2_hand_solved(self):
        # 2x + y = 5, x - y = 1  ->  x=2, y=1
        x = solve([[2, 1], [1, -1]], [5, 1])
        self.assertTrue(close(x[0], 2) and close(x[1], 1))

    def test_identity(self):
        n = 6
        A = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        b = [float(i) for i in range(n)]
        x = solve(A, b)
        self.assertEqual(x, b)

    def test_complex_solve(self):
        # (1+1j)*x = (2+2j)  ->  x = 2
        x = solve([[1 + 1j]], [2 + 2j])
        self.assertTrue(close(abs(x[0] - 2), 0, abs_tol=1e-9))

    def test_singular_raises(self):
        with self.assertRaises(SingularMatrixError):
            solve([[1, 1], [1, 1]], [1, 2])

    def test_random_systems_vs_hand_check(self):
        import random
        rng = random.Random(42)
        for _ in range(30):
            n = rng.randint(2, 8)
            A = [[rng.uniform(-10, 10) for _ in range(n)] for _ in range(n)]
            for i in range(n):
                A[i][i] += 20  # diagonally dominant -> guaranteed nonsingular
            b = [rng.uniform(-10, 10) for _ in range(n)]
            x = solve(A, b)
            # residual check: does Ax actually equal b?
            for i in range(n):
                lhs = sum(A[i][j] * x[j] for j in range(n))
                self.assertTrue(close(lhs, b[i], rel=1e-6, abs_tol=1e-6))


class DCTests(unittest.TestCase):
    def test_voltage_divider(self):
        c = circuits.voltage_divider(10, 1000, 3000)
        v, i = dc.operating_point(c)
        self.assertTrue(close(v["2"], 10 * 3000 / 4000))
        self.assertTrue(close(v["1"], 10.0))

    def test_voltage_divider_various_ratios(self):
        for r1, r2 in [(1, 1), (1, 9), (100, 1), (47, 53)]:
            c = circuits.voltage_divider(12.0, r1 * 1000, r2 * 1000)
            v, _ = dc.operating_point(c)
            expected = 12.0 * r2 / (r1 + r2)
            self.assertTrue(close(v["2"], expected, rel=1e-9),
                             f"r1={r1}k r2={r2}k: got {v['2']}, expected {expected}")

    def test_resistor_bridge_kcl(self):
        c = circuits.resistor_bridge(v=9.0, r=470.0)
        v, i = dc.operating_point(c)
        for node in ("2", "3"):
            total = 0.0
            for e in c.elements:
                if isinstance(e, Resistor):
                    if e.n1 == node:
                        total += (v[e.n2] - v[node]) / e.resistance
                    elif e.n2 == node:
                        total += (v[e.n1] - v[node]) / e.resistance
            self.assertTrue(close(total, 0.0, abs_tol=1e-9), f"KCL violated at node {node}: {total}")

    def test_current_source_direct_injection(self):
        # 1mA current source into a 1k resistor to ground -> exactly 1V.
        c = Circuit([ISource.dc("I1", "1", "0", 1e-3), Resistor("R1", "1", "0", 1000.0)])
        v, i = dc.operating_point(c)
        self.assertTrue(close(v["1"], 1.0))

    def test_floating_node_is_singular(self):
        c = Circuit([Resistor("R1", "1", "2", 100.0)])  # no source, no ground path
        with self.assertRaises(SingularMatrixError):
            dc.operating_point(c)

    def test_zero_or_negative_element_values_rejected(self):
        with self.assertRaises(ValueError):
            Resistor("R1", "1", "2", 0.0)
        with self.assertRaises(ValueError):
            Resistor("R1", "1", "2", -5.0)
        with self.assertRaises(ValueError):
            Capacitor("C1", "1", "2", -1e-6)
        with self.assertRaises(ValueError):
            Inductor("L1", "1", "2", 0.0)

    def test_duplicate_name_error_names_the_culprit(self):
        with self.assertRaises(ValueError) as ctx:
            Circuit([VSource.dc("V1", "1", "0", 5), VSource.dc("V1", "2", "0", 3)])
        self.assertIn("V1", str(ctx.exception))


class TransientTests(unittest.TestCase):
    def test_rc_charge_matches_analytic(self):
        r, c_val = 1000.0, 1e-6
        circuit = circuits.rc_step(5.0, r, c_val)
        res = transient.simulate(circuit, t_stop=5e-3, dt=1e-6, use_ic=True)
        RC = r * c_val
        worst = max(abs(res.voltages["2"][i] - 5.0 * (1 - math.exp(-t / RC)))
                    for i, t in enumerate(res.times))
        self.assertLess(worst, 5e-3)

    def test_rc_discharge_matches_analytic(self):
        # Same RC, but starting fully charged and no drive (V1=0): pure decay.
        r, c_val = 1000.0, 1e-6
        circuit = Circuit([
            VSource.dc("V1", "1", "0", 0.0),
            Resistor("R1", "1", "2", r),
            Capacitor("C1", "2", "0", c_val, ic=5.0),
        ])
        res = transient.simulate(circuit, t_stop=5e-3, dt=1e-6, use_ic=True)
        RC = r * c_val
        worst = max(abs(res.voltages["2"][i] - 5.0 * math.exp(-t / RC))
                    for i, t in enumerate(res.times))
        self.assertLess(worst, 5e-3)

    def test_rl_step_matches_analytic(self):
        r, l = 100.0, 0.1
        circuit = circuits.rl_step(5.0, r, l)
        res = transient.simulate(circuit, t_stop=5e-3, dt=1e-6, use_ic=True)
        tau = l / r
        worst = max(abs(res.currents["L1"][i] - (5.0 / r) * (1 - math.exp(-t / tau)))
                    for i, t in enumerate(res.times))
        self.assertLess(worst, 1e-4)

    def test_default_operating_point_start_is_dc_steady_state(self):
        # Without use_ic, a constant-DC-driven RC circuit starts already
        # charged (open-circuit capacitor at DC == no current == no drop).
        circuit = circuits.rc_step(5.0, 1000.0, 1e-6)
        res = transient.simulate(circuit, t_stop=1e-3, dt=1e-6)
        self.assertTrue(all(close(v, 5.0) for v in res.voltages["2"]))

    def test_dt_larger_than_tstop_raises(self):
        with self.assertRaises(ValueError):
            transient.simulate(circuits.rc_step(), t_stop=1e-9, dt=1e-6)

    def test_negative_dt_or_tstop_raises(self):
        with self.assertRaises(ValueError):
            transient.simulate(circuits.rc_step(), t_stop=1e-3, dt=-1e-6)
        with self.assertRaises(ValueError):
            transient.simulate(circuits.rc_step(), t_stop=-1e-3, dt=1e-6)

    def test_use_ic_current_series_stay_aligned_with_time_series(self):
        # Regression: substituting a Capacitor with a same-named VSource
        # for the t=0 IC snapshot used to leak a phantom one-sample-long
        # "C1" branch-current series into the result, desyncing it from
        # every other series for the rest of the run (caught by demo.sh,
        # which actually writes and measures a full CSV instead of just
        # checking a handful of hand-picked timesteps).
        for name, factory in circuits.PRESETS.items():
            circuit = factory()
            res = transient.simulate(circuit, t_stop=1e-3, dt=1e-6, use_ic=True)
            for branch, series in res.currents.items():
                self.assertEqual(len(series), len(res.times),
                                  f"{name}: I({branch}) has {len(series)} samples, "
                                  f"expected {len(res.times)}")


class DiodeTests(unittest.TestCase):
    def test_half_wave_rectifier_clips_negative_half(self):
        circuit = circuits.half_wave_rectifier(v_amp=10.0, freq=60.0, r=1000.0)
        res = transient.simulate(circuit, t_stop=2 / 60, dt=1e-5)
        self.assertGreater(max(res.voltages["out"]), 9.0)
        self.assertLess(min(res.voltages["out"]), 0.01)
        self.assertGreater(min(res.voltages["out"]), -0.05)

    def test_diode_iv_curve_is_monotonic_and_matches_shockley(self):
        d = Diode("D1", "a", "b")
        prev = None
        for vd in [x / 100 for x in range(-100, 80, 2)]:
            i_d = d.current(vd)
            expected = d.Is * (math.exp(vd / d.nVt) - 1.0)
            self.assertTrue(close(i_d, expected, rel=1e-9))
            if prev is not None:
                self.assertGreaterEqual(i_d, prev)
            prev = i_d

    def test_diode_bad_parameters_rejected(self):
        with self.assertRaises(ValueError):
            Diode("D1", "a", "b", Is=0)
        with self.assertRaises(ValueError):
            Diode("D1", "a", "b", Is=-1e-14)
        with self.assertRaises(ValueError):
            Diode("D1", "a", "b", n=0)
        with self.assertRaises(ValueError):
            Diode("D1", "a", "b", Vt=0)

    def test_reverse_biased_diode_does_not_go_singular(self):
        # D1 is node "2"'s *only* connection — with gmin=0 this would be a
        # singular matrix at deep reverse bias (see REVIEW.md finding #3).
        circuit = Circuit([
            VSource.dc("V1", "1", "0", -80.0),
            Diode("D1", "1", "2"),  # cathode "2" floats except through D1
        ])
        v, i = dc.operating_point(circuit)
        self.assertLess(v["2"], 0)  # pulled negative by gmin leakage, not floating


class ACTests(unittest.TestCase):
    def test_rc_lowpass_cutoff(self):
        r, c_val = 1000.0, 100e-9
        fc = 1 / (2 * math.pi * r * c_val)
        circuit = circuits.rc_lowpass(1.0, r, c_val)
        result = ac.sweep(circuit, fc, fc, 1)
        self.assertTrue(close(result.magnitude("out")[0], 1 / math.sqrt(2), rel=1e-3))
        self.assertTrue(close(result.phase_deg("out")[0], -45.0, rel=1e-2))

    def test_rc_lowpass_rolls_off_at_high_frequency(self):
        circuit = circuits.rc_lowpass(1.0, 1000.0, 100e-9)
        result = ac.sweep(circuit, 1, 10_000_000, 30)
        self.assertTrue(close(result.magnitude("out")[0], 1.0, rel=1e-3))  # DC: passes through
        self.assertLess(result.magnitude("out")[-1], 0.01)  # far above cutoff: heavily attenuated

    def test_rlc_resonance_frequency(self):
        l, c_val = 1e-3, 1e-6
        f0 = 1 / (2 * math.pi * math.sqrt(l * c_val))
        circuit = circuits.rlc_series(v=5.0, r=10.0, l=l, c=c_val, ac_mag=1.0)
        result = ac.sweep(circuit, f0 / 20, f0 * 20, 400)
        currents = [abs(x) for x in result.currents["V1"]]
        peak_f = result.freqs[max(range(len(currents)), key=lambda i: currents[i])]
        self.assertTrue(close(peak_f, f0, rel=0.02))

    def test_magnitude_db_never_returns_infinite(self):
        result = ac.sweep(circuits.rc_lowpass(), 1, 1e6, 10)
        for db in result.magnitude_db("0"):  # ground: always exactly 0V
            self.assertTrue(math.isfinite(db))
        encoded = json.dumps(result.magnitude_db("0"))
        self.assertNotIn("Infinity", encoded)

    def test_diode_in_ac_circuit_raises_clear_error(self):
        circuit = circuits.half_wave_rectifier()
        with self.assertRaises(ValueError):
            ac.sweep(circuit, 60, 60, 1)

    def test_invalid_sweep_ranges_rejected(self):
        circuit = circuits.rc_lowpass()
        with self.assertRaises(ValueError):
            ac.sweep(circuit, 0, 100, 5)
        with self.assertRaises(ValueError):
            ac.sweep(circuit, 100, 1, 5)


class OpAmpTests(unittest.TestCase):
    def test_inverting_gain(self):
        for r_in, r_f in [(1000, 10000), (2200, 2200), (100, 1e6)]:
            circuit = circuits.inverting_amplifier(v_amp=1.0, r_in=r_in, r_f=r_f)
            result = ac.sweep(circuit, 1000, 1000, 1)
            gain = result.voltages["out"][0] / result.voltages["in"][0]
            self.assertTrue(close(gain, -r_f / r_in, rel=1e-6))

    def test_noninverting_gain(self):
        for r_in, r_f in [(1000, 10000), (2200, 2200), (100, 1e6)]:
            circuit = circuits.noninverting_amplifier(v_amp=1.0, r_in=r_in, r_f=r_f)
            result = ac.sweep(circuit, 1000, 1000, 1)
            gain = result.voltages["out"][0] / result.voltages["in"][0]
            self.assertTrue(close(gain, 1 + r_f / r_in, rel=1e-6))

    def test_unity_buffer(self):
        # non-inverting amp with Rf=0, Rin=infinite (omitted) is a unity
        # buffer: op-amp output directly follows its + input.
        circuit = Circuit([
            VSource("V1", "in", "0", dc_value=0.0, ac_mag=1.0),
            OpAmp("O1", "in", "out", "out"),
        ])
        result = ac.sweep(circuit, 1000, 1000, 1)
        self.assertTrue(close(result.voltages["out"][0] / result.voltages["in"][0], 1.0))


class NetlistTests(unittest.TestCase):
    def test_value_suffixes(self):
        cases = {"1k": 1000.0, "4.7u": 4.7e-6, "10meg": 10e6, "1m": 1e-3,
                 "100n": 100e-9, "1p": 1e-12, "2.2f": 2.2e-15, "5": 5.0,
                 "-3.3": -3.3, "1e3": 1000.0}
        for text, expected in cases.items():
            self.assertTrue(close(netlist.parse_value(text), expected, rel=1e-9),
                             f"{text} -> {netlist.parse_value(text)}, expected {expected}")

    def test_round_trip_every_preset(self):
        for name, factory in circuits.PRESETS.items():
            original = factory()
            text = netlist.to_netlist(original.elements, title=name)
            elements2, _ = netlist.parse_netlist(text)
            reimported = Circuit(elements2, name=name)
            v1, _ = dc.operating_point(original)
            v2, _ = dc.operating_point(reimported)
            for node in v1:
                self.assertTrue(close(v1[node], v2[node], abs_tol=1e-6),
                                 f"{name}: node {node} diverged after round-trip")

    def test_pulse_and_sin_round_trip_exactly(self):
        original = VSource.sine("V1", "in", "0", offset=1.0, amplitude=5.0,
                                 freq=60.0, delay=0.001, damping=0.5)
        text = netlist.to_netlist([original])
        elements2, _ = netlist.parse_netlist(text)
        reimported = elements2[0]
        for t in [0.0, 0.0005, 0.002, 0.01, 0.1]:
            self.assertTrue(close(original.value_at(t), reimported.value_at(t), abs_tol=1e-9))

        pulse = VSource.pulse("V2", "in", "0", 0.0, 5.0, 1e-3, 1e-4, 1e-4, 2e-3, 5e-3)
        text2 = netlist.to_netlist([pulse])
        elements3, _ = netlist.parse_netlist(text2)
        reimported2 = elements3[0]
        for t in [0.0, 5e-4, 1.05e-3, 2.5e-3, 6e-3]:
            self.assertTrue(close(pulse.value_at(t), reimported2.value_at(t), abs_tol=1e-9))

    def test_ac_spec_round_trip(self):
        original = VSource("V1", "in", "0", dc_value=2.0, ac_mag=1.5, ac_phase_deg=0.0)
        text = netlist.to_netlist([original])
        self.assertIn("AC 1.5", text)
        elements2, _ = netlist.parse_netlist(text)
        self.assertTrue(close(elements2[0].ac_mag, 1.5))

    def test_comments_and_directives(self):
        text = "* a comment\nR1 1 0 1k ; trailing comment\n.tran 1u 5m\n.end"
        elements, directives = netlist.parse_netlist(text)
        self.assertEqual(len(elements), 1)
        self.assertEqual(directives, [("tran", ["1u", "5m"]), ("end", [])])

    def test_malformed_lines_raise_with_line_number(self):
        with self.assertRaises(ValueError) as ctx:
            netlist.parse_netlist("R1 1 0 1k\nZ1 garbage line\n")
        self.assertIn("line 2", str(ctx.exception))

    def test_diode_kv_params(self):
        elements, _ = netlist.parse_netlist("D1 a b IS=2e-9 N=1.5")
        d = elements[0]
        self.assertTrue(close(d.Is, 2e-9))
        self.assertTrue(close(d.n, 1.5))

    def test_opamp_needs_three_nodes(self):
        with self.assertRaises(ValueError):
            netlist.parse_netlist("O1 a b")


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def _post(self, path, payload):
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_index_page_served(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Faraday", body)

    def test_presets_endpoint_matches_python_presets(self):
        status, body = self._get("/api/presets")
        self.assertEqual(status, 200)
        presets = json.loads(body)
        self.assertEqual(set(presets), set(circuits.PRESETS))

    def test_simulate_dc(self):
        status, data = self._post("/api/simulate", {
            "netlist": "V1 1 0 DC 10\nR1 1 2 1000\nR2 2 0 1000\n",
            "analysis": "dc",
        })
        self.assertEqual(status, 200)
        self.assertTrue(close(data["voltages"]["2"], 5.0))

    def test_simulate_ac_response_is_valid_json_with_no_infinities(self):
        status, data = self._post("/api/simulate", {
            "netlist": netlist.to_netlist(circuits.rc_lowpass().elements),
            "analysis": "ac", "fstart": 1, "fstop": 1e6, "points": 20,
        })
        self.assertEqual(status, 200)
        for series in data["magnitude_db"].values():
            self.assertTrue(all(v is None or math.isfinite(v) for v in series))

    def test_simulate_rejects_bad_netlist_cleanly(self):
        status, data = self._post("/api/simulate", {"netlist": "garbage", "analysis": "dc"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_simulate_rejects_unknown_analysis(self):
        status, data = self._post("/api/simulate", {"netlist": "R1 1 0 1k", "analysis": "bogus"})
        self.assertEqual(status, 400)

    def test_transient_step_count_guard(self):
        status, data = self._post("/api/simulate", {
            "netlist": "V1 1 0 DC 5\nR1 1 0 1k\n",
            "analysis": "tran", "tstop": 1.0, "dt": 1e-9,  # 1e9 steps
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_unknown_route_404s(self):
        status, _ = self._get("/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
