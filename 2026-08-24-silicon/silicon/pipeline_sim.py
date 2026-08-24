"""A cycle-accurate 5-stage (IF/ID/EX/MEM/WB) in-order pipeline simulator
for the RV32I subset, with:

  * full RAW-hazard forwarding: EX/MEM -> EX and MEM/WB -> EX, plus a
    same-cycle "write in the first half, read in the second half" register
    file convention that resolves the WB -> ID case for free (the classic
    simplification used by every 5-stage-pipeline textbook diagram);
  * a load-use hazard detector that stalls exactly one cycle when
    forwarding alone can't get the data there in time;
  * branch/jalr resolution in EX (2-cycle misprediction penalty) and early
    jal resolution in ID (1-cycle penalty, since jal's target needs no
    register read);
  * optional L1 instruction/data caches wired into IF/MEM timing: a miss
    freezes the pipeline for `mem_miss_latency` cycles instead of 1.

Each pipeline register (IF/ID, ID/EX, EX/MEM, MEM/WB) is a plain dict, or
`None` for a bubble. Every cycle computes *proposed* new latch contents from
the *current* (start-of-cycle) ones, then commits them all at once -- the
same simultaneous-update discipline a real synchronous circuit has, so
there's no risk of a stage accidentally reading a value another stage
already updated this cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import alu, isa
from .assembler import AssembledProgram
from .branch_predictor import make_predictor
from .cache import Cache
from .functional_sim import SimulatorTrap
from .memory import Memory, RegisterFile


@dataclass
class RetiredPipelineInstr:
    pc: int
    word: int
    mnemonic: str
    text: str = ""


@dataclass
class PipelineStats:
    cycles: int = 0
    instret: int = 0
    load_use_stall_cycles: int = 0
    mem_stall_cycles: int = 0
    mispredictions: int = 0
    flushed_instructions: int = 0
    branches_resolved: int = 0

    @property
    def cpi(self) -> float:
        return self.cycles / self.instret if self.instret else 0.0


class PipelineSimulator:
    def __init__(
        self,
        program: AssembledProgram,
        mem_size: int = 1 << 20,
        predictor_kind: str = "dynamic",
        icache: Optional[Cache] = None,
        dcache: Optional[Cache] = None,
        mem_miss_latency: int = 10,
        trace_cycles: bool = False,
    ):
        self.mem = Memory(mem_size)
        self.regs = RegisterFile()
        for i, word in enumerate(program.words):
            self.mem.store_word(program.base_address + 4 * i, word)
        self.program = program
        self.pc = program.base_address

        self.predictor = make_predictor(predictor_kind)
        self.icache = icache
        self.dcache = dcache
        self.mem_miss_latency = max(1, mem_miss_latency)

        # pipeline latches (None == bubble)
        self.if_id: Optional[dict] = None
        self.id_ex: Optional[dict] = None
        self.ex_mem: Optional[dict] = None
        self.mem_wb: Optional[dict] = None

        self._if_pending: Optional[dict] = None  # in-progress icache-miss fetch
        self._next_seq = 0  # unique id per dynamic instruction instance, for the visualizer
        self._pending_flush = None  # (stage, target_pc) or None, reset each cycle

        self.fetch_halted = False
        self.halted = False
        self.instret = 0
        self.trace: List[RetiredPipelineInstr] = []
        self.stats = PipelineStats()

        # optional per-cycle snapshot log for the HTML visualizer
        self.trace_cycles = trace_cycles
        self.cycle_log: List[dict] = []

    # -----------------------------------------------------------------
    # top-level driver
    # -----------------------------------------------------------------

    def run(self, max_cycles: int = 5_000_000) -> int:
        cycles = 0
        while not self.halted and cycles < max_cycles:
            self.cycle()
            cycles += 1
        if not self.halted:
            raise SimulatorTrap(f"pipeline did not halt within {max_cycles} cycles")
        return cycles

    def state_fingerprint(self) -> tuple:
        return (self.regs.snapshot(), bytes(self.mem.data))

    # -----------------------------------------------------------------
    # one clock cycle
    # -----------------------------------------------------------------

    def cycle(self) -> None:
        if self.halted:
            return
        self._pending_flush = None

        # ---- MEM stage: may discover a multi-cycle cache-miss stall ----
        new_mem_wb, mem_stalling = self._run_mem_stage()

        if mem_stalling:
            # A data-cache miss freezes everything upstream: IF/ID, ID/EX,
            # EX/MEM all hold their current contents; only WB keeps
            # draining whatever had already reached MEM/WB before the
            # stall began.
            retired = self.mem_wb
            self._do_writeback(self.mem_wb)
            if self.trace_cycles:
                self._log_cycle(self.if_id, self.id_ex, self.ex_mem, None, retired, stalled="mem")
            self.mem_wb = None
            self.stats.mem_stall_cycles += 1
            self.stats.cycles += 1
            return

        # ---- retire (WB happens before ID reads registers this cycle) ----
        retired = self.mem_wb
        self._do_writeback(self.mem_wb)

        # ---- load-use hazard check (uses *current* id_ex / if_id) ----
        load_use = self._detect_load_use_hazard()

        # ---- EX stage: forwarding + ALU + branch/jalr resolution ----
        new_ex_mem = self._run_ex_stage(self.id_ex)

        # ---- ID stage (skipped -- held -- on a load-use stall) ----
        if load_use:
            new_id_ex = None
        else:
            new_id_ex = self._run_id_stage(self.if_id)

        # ---- IF stage (held on a load-use stall: no new fetch attempt) ----
        if load_use:
            new_if_id = self.if_id
            next_pc = self.pc
        else:
            new_if_id, next_pc = self._run_if_stage(self.pc)

        # ---- resolve any control-flow flush, which overrides ID/IF ----
        if self._pending_flush is not None:
            stage, target = self._pending_flush
            self._if_pending = None
            if stage == "EX":
                new_id_ex = None
                new_if_id = None
                self.stats.flushed_instructions += 2
            else:  # "ID" (jal, resolved early)
                new_if_id = None
                self.stats.flushed_instructions += 1
            next_pc = target

        # An ecall only *actually* stops further fetching once we know the
        # instruction that decoded to it survived all the way past ID
        # without being squashed -- checking any earlier (e.g. right after
        # IF) is provably too soon: an indirect jump (jalr/ret) resolves in
        # EX, one cycle *after* the instruction right behind it is already
        # sitting in ID, so a speculatively-fetched word that happens to
        # decode as ecall (this can and does happen for real, e.g. a `ret`
        # whose not-yet-learned not-taken prediction free-falls straight
        # into the next thing after it in memory, which may well *be* the
        # program's real, final ecall at a different point in the control
        # flow) can still be discarded by a flush one cycle later. Once it
        # reaches EX unflushed, nothing can retroactively squash it -- only
        # id_ex/if_id are ever flush targets in this design -- so this is
        # the earliest point a halt decision is provably final.
        if new_id_ex is not None and not new_id_ex.get("illegal") and new_id_ex["mnemonic"] == "ecall":
            self.fetch_halted = True
            # The fetch IF issued this very cycle (immediately after the
            # now-confirmed-real ecall) reads whatever memory happens to
            # follow the program's last word -- never a real instruction --
            # so discard it now rather than let it drift into ID next cycle
            # and (having nothing left to flush it) wrongly fault as a
            # retired illegal instruction.
            new_if_id = None
            self._if_pending = None

        if self.trace_cycles:
            self._log_cycle(
                new_if_id, new_id_ex, new_ex_mem, new_mem_wb, retired,
                stalled="load_use" if load_use else None,
            )

        # ---- commit all latches simultaneously ----
        self.mem_wb = new_mem_wb
        self.ex_mem = new_ex_mem
        self.id_ex = new_id_ex
        self.if_id = new_if_id
        self.pc = next_pc

        if load_use:
            self.stats.load_use_stall_cycles += 1
        self.stats.cycles += 1

    # -----------------------------------------------------------------
    # stage implementations
    # -----------------------------------------------------------------

    def _run_if_stage(self, pc: int):
        if self.fetch_halted:
            return None, pc

        if self._if_pending is None:
            if self.icache is not None:
                hit = self.icache.access(pc)
            else:
                hit = True
            if not hit:
                self._if_pending = {"pc": pc, "remaining": self.mem_miss_latency - 1}
                return None, pc
        else:
            self._if_pending["remaining"] -= 1
            if self._if_pending["remaining"] > 0:
                return None, pc
            pc = self._if_pending["pc"]
            self._if_pending = None

        word = self.mem.load_word(pc)
        # NOTE: we deliberately do *not* decode/validate the word here, even
        # though decoding is needed to make a real branch prediction. A
        # speculatively-fetched word (e.g. the fall-through after a jal/jalr
        # the predictor hasn't learned yet) can easily be genuine *garbage*
        # -- the pipeline just hasn't discovered the misprediction yet -- and
        # in-order hardware never faults on a fetch that later gets squashed.
        # So decode failures are caught softly and only turn into a real
        # SimulatorTrap in _do_writeback, if the bad instruction actually
        # reaches retirement (i.e. was never on a squashed path at all).
        try:
            isa.decode(word)
            illegal = False
        except ValueError:
            illegal = True

        pred_taken, pred_target = self.predictor.predict(pc)
        next_pc = pred_target if (pred_taken and pred_target is not None) else isa.to_u32(pc + 4)

        entry = {
            "pc": pc, "word": word, "pred_taken": pred_taken, "pred_target": pred_target,
            "illegal": illegal, "seq": self._next_seq,
        }
        self._next_seq += 1
        return entry, next_pc

    def _detect_load_use_hazard(self) -> bool:
        if self.id_ex is None or not self.id_ex.get("is_load") or self.id_ex["rd"] == 0:
            return False
        if self.if_id is None or self.if_id["illegal"]:
            return False
        d = isa.decode(self.if_id["word"])
        needed = set()
        if d.uses_rs1():
            needed.add(d.rs1)
        if d.uses_rs2():
            needed.add(d.rs2)
        return self.id_ex["rd"] in needed

    def _run_id_stage(self, if_id: Optional[dict]) -> Optional[dict]:
        if if_id is None:
            return None
        pc, word = if_id["pc"], if_id["word"]
        if if_id["illegal"]:
            # Might still be squashed by a flush this very cycle (the
            # branch/jalr that mis-speculated this fetch typically resolves
            # 1-2 cycles later); only a real retirement turns this into a
            # SimulatorTrap. See _do_writeback.
            return {
                "pc": pc, "word": word, "mnemonic": "?ILLEGAL", "fmt": "SYS",
                "rd": 0, "rs1_num": 0, "rs2_num": 0, "rs1_val": 0, "rs2_val": 0,
                "imm": 0, "funct3": 0, "is_load": False, "writes_rd": False,
                "pred_taken": if_id["pred_taken"], "pred_target": if_id["pred_target"],
                "text": "<illegal>", "illegal": True, "seq": if_id["seq"],
            }
        d = isa.decode(word)
        rs1_val = self.regs.read(d.rs1) if d.uses_rs1() else 0
        rs2_val = self.regs.read(d.rs2) if d.uses_rs2() else 0
        text = self.program.text.get((pc - self.program.base_address) // 4, d.mnemonic)

        entry = {
            "pc": pc, "word": word, "mnemonic": d.mnemonic, "fmt": d.fmt,
            "rd": d.rd, "rs1_num": d.rs1 if d.uses_rs1() else 0,
            "rs2_num": d.rs2 if d.uses_rs2() else 0,
            "rs1_val": rs1_val, "rs2_val": rs2_val, "imm": d.imm, "funct3": d.funct3,
            "is_load": d.mnemonic in isa.LOAD_TYPE, "writes_rd": d.writes_rd(),
            "pred_taken": if_id["pred_taken"], "pred_target": if_id["pred_target"],
            "text": text, "illegal": False, "seq": if_id["seq"],
        }

        if d.mnemonic == "jal":
            actual_target = isa.to_u32(pc + d.imm)
            self.stats.branches_resolved += 1
            self.predictor.update(pc, True, actual_target)
            predicted_ok = if_id["pred_taken"] and if_id["pred_target"] == actual_target
            if not predicted_ok:
                self.stats.mispredictions += 1
                # EX already runs before ID every cycle (see cycle()), so if
                # EX just flagged its own flush this cycle, that flush is
                # for an OLDER in-flight instruction (whatever is in EX is
                # always ahead of whatever is in ID) and always wins: it
                # already discards this jal's own successor anyway (an EX
                # flush squashes id_ex AND if_id, a strict superset of what
                # this ID-stage flush would squash). Setting ours here would
                # silently clobber the correct, higher-priority redirect
                # target with this jal's -- exactly the bug a fixed test
                # program (bubblesort.s) caught: a mispredicted `blt`
                # immediately followed by the unconditional `j` it should
                # have skipped over entirely.
                if self._pending_flush is None:
                    self._pending_flush = ("ID", actual_target)

        return entry

    def _forward(self, reg_num: int, raw_val: int) -> int:
        if reg_num == 0:
            return 0
        em = self.ex_mem
        if em is not None and em.get("writes_rd") and em["rd"] == reg_num and not em.get("is_load"):
            return em["alu_result"]
        mw = self.mem_wb
        if mw is not None and mw.get("writes_rd") and mw["rd"] == reg_num:
            return mw["result"]
        return raw_val

    def _run_ex_stage(self, id_ex: Optional[dict]) -> Optional[dict]:
        if id_ex is None:
            return None
        mnemonic, fmt = id_ex["mnemonic"], id_ex["fmt"]
        rs1v = self._forward(id_ex["rs1_num"], id_ex["rs1_val"])
        rs2v = self._forward(id_ex["rs2_num"], id_ex["rs2_val"])
        pc = id_ex["pc"]

        out = {
            "pc": pc, "word": id_ex["word"], "mnemonic": mnemonic,
            "rd": id_ex["rd"], "writes_rd": id_ex["writes_rd"], "text": id_ex["text"],
            "is_load": False, "is_store": False, "illegal": id_ex.get("illegal", False),
            "seq": id_ex["seq"],
        }

        if out["illegal"]:
            out["alu_result"] = 0
            return out

        if fmt == "R":
            out["alu_result"] = alu.alu_op(mnemonic, rs1v, rs2v)
        elif mnemonic in isa.I_ALU_TYPE:
            out["alu_result"] = alu.alu_op(mnemonic, rs1v, isa.to_u32(id_ex["imm"]))
        elif mnemonic in isa.LOAD_TYPE:
            out["is_load"] = True
            out["mem_addr"] = isa.to_u32(rs1v + id_ex["imm"])
            out["funct3"] = id_ex["funct3"]
            out["mem_charged"] = False
            out["mem_extra_stall"] = 0
        elif mnemonic in isa.STORE_TYPE:
            out["is_store"] = True
            out["mem_addr"] = isa.to_u32(rs1v + id_ex["imm"])
            out["store_data"] = rs2v
            out["funct3"] = id_ex["funct3"]
            out["mem_charged"] = False
            out["mem_extra_stall"] = 0
        elif mnemonic in isa.BRANCH_TYPE:
            taken = alu.branch_taken(mnemonic, rs1v, rs2v)
            target = isa.to_u32(pc + id_ex["imm"]) if taken else isa.to_u32(pc + 4)
            out["alu_result"] = 0
            self._resolve_control(id_ex, taken, target)
        elif mnemonic == "jalr":
            target = isa.to_u32(rs1v + id_ex["imm"]) & ~1
            out["alu_result"] = isa.to_u32(pc + 4)
            self._resolve_control(id_ex, True, target)
        elif mnemonic == "jal":
            out["alu_result"] = isa.to_u32(pc + 4)  # control already resolved in ID
        elif mnemonic == "lui":
            out["alu_result"] = isa.to_u32(id_ex["imm"])
        elif mnemonic == "auipc":
            out["alu_result"] = isa.to_u32(pc + id_ex["imm"])
        elif mnemonic == "ecall":
            out["alu_result"] = 0
        else:
            raise SimulatorTrap(f"EX: unhandled mnemonic {mnemonic!r}")

        return out

    def _resolve_control(self, id_ex: dict, actual_taken: bool, actual_target: int) -> None:
        self.stats.branches_resolved += 1
        pc = id_ex["pc"]
        self.predictor.update(pc, actual_taken, actual_target)
        predicted_taken = id_ex["pred_taken"]
        predicted_target = id_ex["pred_target"]
        predicted_ok = (predicted_taken == actual_taken) and (
            not actual_taken or predicted_target == actual_target
        )
        if not predicted_ok:
            self._pending_flush = ("EX", actual_target)
            self.stats.mispredictions += 1

    def _run_mem_stage(self):
        instr = self.ex_mem
        if instr is None:
            return None, False

        if instr["is_load"] or instr["is_store"]:
            if self.dcache is not None:
                if not instr["mem_charged"]:
                    hit = self.dcache.access(instr["mem_addr"])
                    instr["mem_charged"] = True
                    if not hit:
                        instr["mem_extra_stall"] = self.mem_miss_latency - 1
                if instr["mem_extra_stall"] > 0:
                    instr["mem_extra_stall"] -= 1
                    return None, True

        return self._complete_mem(instr), False

    def _complete_mem(self, instr: dict) -> dict:
        if instr["is_load"]:
            addr, mn = instr["mem_addr"], instr["mnemonic"]
            if mn == "lb":
                val = self.mem.load_byte(addr, signed=True)
            elif mn == "lbu":
                val = self.mem.load_byte(addr, signed=False)
            elif mn == "lh":
                val = self.mem.load_half(addr, signed=True)
            elif mn == "lhu":
                val = self.mem.load_half(addr, signed=False)
            else:  # lw
                val = self.mem.load_word(addr)
            result = isa.to_u32(val)
        elif instr["is_store"]:
            addr, mn, data = instr["mem_addr"], instr["mnemonic"], instr["store_data"]
            if mn == "sb":
                self.mem.store_byte(addr, data)
            elif mn == "sh":
                self.mem.store_half(addr, data)
            else:  # sw
                self.mem.store_word(addr, data)
            result = 0
        else:
            result = instr["alu_result"]

        return {
            "pc": instr["pc"], "word": instr["word"], "mnemonic": instr["mnemonic"],
            "rd": instr["rd"], "writes_rd": instr["writes_rd"], "result": result,
            "text": instr["text"], "illegal": instr.get("illegal", False), "seq": instr["seq"],
        }

    def _do_writeback(self, mem_wb: Optional[dict]) -> None:
        if mem_wb is None:
            return
        if mem_wb["illegal"]:
            # A genuinely illegal instruction survived all the way to
            # retirement -- i.e. it was never on a squashed speculative
            # path after all. This is a real fault, not a prediction
            # artifact (those never reach here; see _run_if_stage).
            raise SimulatorTrap(f"illegal instruction retired @0x{mem_wb['pc']:x}: 0x{mem_wb['word']:08x}")
        if mem_wb["writes_rd"] and mem_wb["rd"] != 0:
            self.regs.write(mem_wb["rd"], mem_wb["result"])
        self.instret += 1
        self.stats.instret += 1
        self.trace.append(RetiredPipelineInstr(mem_wb["pc"], mem_wb["word"], mem_wb["mnemonic"], mem_wb["text"]))
        if mem_wb["mnemonic"] == "ecall":
            self.halted = True

    # -----------------------------------------------------------------
    # visualizer support
    # -----------------------------------------------------------------

    def _log_cycle(self, if_id, id_ex, ex_mem, mem_wb, retired, stalled: Optional[str]) -> None:
        def summarize(slot):
            if slot is None:
                return None
            return {
                "pc": slot.get("pc"), "seq": slot.get("seq"),
                "text": slot.get("text", slot.get("mnemonic", "?")),
            }

        self.cycle_log.append({
            "cycle": self.stats.cycles,
            "IF": summarize(if_id),
            "ID": summarize(id_ex),
            "EX": summarize(ex_mem),
            "MEM": summarize(mem_wb),
            "WB": summarize(retired),
            "stalled": stalled,
            "flush": self._pending_flush[0] if self._pending_flush else None,
        })
