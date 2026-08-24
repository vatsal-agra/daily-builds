"""One test per real bug found during adversarial review (REVIEW.md),
each reproducing the exact failure mode directly rather than only relying
on the broader program-level cross-check to happen to catch it again.
"""

import unittest

from silicon.assembler import assemble
from silicon.functional_sim import FunctionalSimulator, SimulatorTrap
from silicon.pipeline_sim import PipelineSimulator
from silicon import isa


class TestRegressions(unittest.TestCase):
    def test_speculative_ecall_fetch_does_not_wedge_the_pipeline(self):
        # bug #1: a `ret` whose predicted-not-taken fall-through happens to
        # read a *real* ecall elsewhere in the program must not
        # permanently stop fetching if that ret's actual target is
        # somewhere else entirely.
        src = """
        li a0, 3
        call double
        sw a0, 0(x0)
        ecall
        double:
        add a0, a0, a0
        ret
        """
        prog = assemble(src)
        sim = PipelineSimulator(prog, predictor_kind="static")
        sim.run(max_cycles=1000)  # must not hit the cycle cap
        self.assertTrue(sim.halted)
        self.assertEqual(sim.mem.load_word(0), 6)

    def test_genuinely_illegal_instruction_still_traps_if_it_retires(self):
        # the flip side of bug #2's fix: a *real* illegal instruction that
        # is never on a squashed path must still raise, not be silently
        # swallowed by the new soft-decode-failure machinery.
        prog = assemble("nop\necall\n")
        prog.words[0] = 0x00000000  # illegal opcode, replacing the nop directly
        sim = PipelineSimulator(prog, predictor_kind="static")
        with self.assertRaises(SimulatorTrap):
            sim.run(max_cycles=1000)

    def test_speculative_illegal_fetch_past_end_of_program_does_not_crash(self):
        # bug #2: a speculative over-fetch into zeroed post-program memory
        # must not crash the simulator outright.
        src = "li a0, 1\ncall f\necall\nf:\nadd a0, a0, a0\nret\n"
        sim = PipelineSimulator(assemble(src), predictor_kind="static")
        sim.run(max_cycles=1000)  # must not raise
        self.assertTrue(sim.halted)

    def test_branch_immediately_followed_by_unconditional_jump(self):
        # bug #3: a conditional branch that mispredicts in EX, with an
        # unconditional `j` (its own not-taken fall-through) sitting right
        # behind it in ID resolving *its own* early flush the same cycle,
        # must not have the branch's flush silently overwritten.
        src = """
        li t0, 5
        li t1, 3
        blt t1, t0, taken
        j not_taken
        taken:
        li a0, 111
        j end
        not_taken:
        li a0, 222
        end:
        ecall
        """
        gold = FunctionalSimulator(assemble(src))
        gold.run()
        pipe = PipelineSimulator(assemble(src), predictor_kind="static")
        pipe.run()
        self.assertEqual(gold.regs.read(isa.reg_num("a0")), 111)
        self.assertEqual(pipe.regs.read(isa.reg_num("a0")), 111)
        self.assertEqual(gold.state_fingerprint(), pipe.state_fingerprint())

    def test_bubblesort_under_static_prediction_matches_golden_model(self):
        # the exact program that originally caught bug #3 in the wild
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "programs" / "bubblesort.s").read_text()
        gold = FunctionalSimulator(assemble(src))
        gold.run()
        pipe = PipelineSimulator(assemble(src), predictor_kind="static")
        pipe.run()
        self.assertEqual(gold.state_fingerprint(), pipe.state_fingerprint())
        self.assertEqual(gold.instret, pipe.instret)

    def test_store_offset_out_of_signed_12_bit_range_rejected(self):
        # bug #4
        with self.assertRaises(Exception):
            assemble("sw t0, 2048(t1)\n")
        assemble("sw t0, 2047(t1)\n")  # boundary value must still work

    def test_unresolved_label_error_reports_its_line(self):
        # bug #5
        from silicon.assembler import AssemblerError
        with self.assertRaises(AssemblerError) as ctx:
            assemble("nop\nnop\nj nosuchlabel\n")
        self.assertEqual(ctx.exception.line_no, 3)

    def test_illegal_instruction_in_functional_sim_raises_clean_trap(self):
        # bug #6 (phase 4 polish): decode failures inside the sequential
        # golden-model simulator used to propagate as a raw ValueError
        # instead of the SimulatorTrap every caller (the CLI included)
        # expects and catches.
        prog = assemble("nop\n")  # no ecall -> falls off the end into zeroed memory
        sim = FunctionalSimulator(prog)
        with self.assertRaises(SimulatorTrap):
            sim.run(max_steps=10)

    def test_cli_demo_subcommand_runs_end_to_end(self):
        # bug #7 (phase 4 polish): `cmd_demo` hand-built argparse Namespace
        # objects for the subcommands it drives, which silently drifted out
        # of sync with a subcommand's real required attributes (missing
        # `max_steps` on the `pipeline --check` call) and crashed with a
        # raw AttributeError. Now it re-enters through the real parser.
        from silicon.cli import build_parser
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ns = build_parser().parse_args(["demo"])
            ns.func(ns)  # must not raise
        self.assertIn("MATCHES sequential golden model", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
