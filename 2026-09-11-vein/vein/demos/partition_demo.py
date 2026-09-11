"""Orchestrates real `vein node start` OS subprocesses — not threads, not
function calls — into a small P2P network, funds a wallet, severs the
network into two groups mid-run, lets each side mine its own competing
fork (including a genuine double-spend attempt: the same coin spent two
different ways on the two sides), heals the partition, and proves every
node converges on one identical chain + UTXO set, with only the
winning side's spend surviving anywhere.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from typing import Dict, List

from ..wallet.wallet import Wallet
from ..core.transaction import TxOut
from ..core.script import Script

RPC_TIMEOUT = 5
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get(base: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base}{path}", timeout=RPC_TIMEOUT) as resp:
        return json.loads(resp.read())


def _post(base: str, path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{base}{path}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=RPC_TIMEOUT) as resp:
        return json.loads(resp.read())


def _wait_for_rpc(base: str, timeout: float = 10) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            _get(base, "/status")
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"node at {base} never came up")


class NodeHandle:
    def __init__(self, name: str, p2p_port: int, rpc_port: int, miner_address: str):
        self.name = name
        self.p2p_port = p2p_port
        self.rpc_port = rpc_port
        self.rpc_base = f"http://127.0.0.1:{rpc_port}"
        self.peer_key = f"127.0.0.1:{p2p_port}"
        self.miner_address = miner_address
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        cmd = [sys.executable, "-m", "vein.cli", "node", "start",
               "--name", self.name,
               "--p2p-port", str(self.p2p_port),
               "--rpc-port", str(self.rpc_port),
               "--miner-address", self.miner_address]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=_PROJECT_ROOT)

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def status(self) -> dict:
        return _get(self.rpc_base, "/status")

    def connect(self, other: "NodeHandle") -> None:
        _post(self.rpc_base, "/connect", {"host": "127.0.0.1", "port": other.p2p_port})

    def sever(self, other: "NodeHandle") -> None:
        _post(self.rpc_base, "/sever", {"peer": other.peer_key})

    def heal(self, other: "NodeHandle") -> None:
        _post(self.rpc_base, "/heal", {"peer": other.peer_key})

    def p2p_resync(self, other: "NodeHandle") -> None:
        _post(self.rpc_base, "/sync", {"peer": other.peer_key})

    def mine_start(self) -> None:
        _post(self.rpc_base, "/mine/start", {})

    def mine_stop(self) -> None:
        _post(self.rpc_base, "/mine/stop", {})

    def balance(self, address: str) -> int:
        return _get(self.rpc_base, f"/balance?address={address}")["balance"]

    def utxos(self, address: str) -> list:
        return _get(self.rpc_base, f"/utxos?address={address}")["utxos"]

    def submit_tx(self, tx_hex: str) -> dict:
        return _post(self.rpc_base, "/submit_tx", {"tx": tx_hex})


def _p(msg: str = "") -> None:
    print(msg)
    sys.stdout.flush()


def run_partition_demo(base_port: int = 19000, target_height_each_side: int = 3,
                        max_wait: float = 90.0) -> None:
    _p("=" * 72)
    _p("VEIN — network partition demo (real OS subprocesses over real TCP)")
    _p("=" * 72)

    miner_wallets = [Wallet.generate() for _ in range(4)]
    names = ["alpha", "beta", "gamma", "delta"]
    nodes = [
        NodeHandle(names[i], base_port + i, base_port + 100 + i, miner_wallets[i].address)
        for i in range(4)
    ]

    try:
        _p("\n[1] starting 4 independent node processes...")
        for n in nodes:
            n.start()
        for n in nodes:
            _wait_for_rpc(n.rpc_base)
            _p(f"    {n.name}: pid={n.proc.pid} p2p=127.0.0.1:{n.p2p_port} rpc={n.rpc_base}")

        _p("\n[2] wiring a full mesh and starting mining on all 4 nodes...")
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                a.connect(b)
        time.sleep(1.0)
        for n in nodes:
            n.mine_start()

        _p("    waiting for the whole network to converge on a shared tip...")
        t0 = time.time()
        # With 4 miners racing, any *particular* one of them (e.g. alpha)
        # isn't guaranteed to have won a block by any fixed height — only
        # that *someone* has. Require enough blocks that, in expectation,
        # several different miners have each won at least one (coinbase
        # outputs mature immediately here, no confirmation depth rule).
        min_height = 4
        while time.time() - t0 < max_wait:
            tips = {n.status()["tip"] for n in nodes}
            heights = [n.status()["height"] for n in nodes]
            funded = any(nodes[0].balance(w.address) > 0 for w in miner_wallets)
            if len(tips) == 1 and min(heights) >= min_height and funded:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("network never converged (with a funded miner) before the partition")
        for n in nodes:
            n.mine_stop()
        shared_height = nodes[0].status()["height"]
        shared_tip = nodes[0].status()["tip"]
        _p(f"    all 4 nodes agree: height={shared_height} tip={shared_tip[:16]}")

        payer = next(w for w in miner_wallets if nodes[0].balance(w.address) > 0)
        payer_balance = nodes[0].balance(payer.address)
        _p(f"    funding wallet ({payer.address[:12]}...) balance: {payer_balance:,} sats")
        utxo_list = nodes[0].utxos(payer.address)
        assert utxo_list, "expected the funding wallet to have spendable coins by now"
        spend_txid, spend_idx, spend_value = (bytes.fromhex(utxo_list[0]["txid"]), utxo_list[0]["index"],
                                               utxo_list[0]["value"])

        _p("\n[3] PARTITIONING the network: {alpha, beta} | {gamma, delta}")
        group1, group2 = nodes[:2], nodes[2:]
        for a in group1:
            for b in group2:
                a.sever(b)
                b.sever(a)
        _p("    (TCP connections stay open — sever() just drops messages both ways,")
        _p("     the same as a real router silently dropping a link)")

        recipient1 = Wallet.generate()
        recipient2 = Wallet.generate()
        _p(f"\n[4] DOUBLE-SPEND ATTEMPT: the same coin ({spend_value:,} sats) spent two")
        _p(f"    different ways, one submitted to each side of the partition:")
        _p(f"      side 1 (alpha/beta)  -> {recipient1.address}")
        _p(f"      side 2 (gamma/delta) -> {recipient2.address}")

        from ..core.transaction import Transaction, TxIn

        def build_spend(to_wallet: Wallet) -> str:
            prevout = TxOut(spend_value, Script.p2pkh_lock(payer.pubkey_hash))
            tx = Transaction(
                inputs=[TxIn(spend_txid, spend_idx, Script([]))],
                outputs=[TxOut(spend_value - 2000, Script.p2pkh_lock(to_wallet.pubkey_hash))],
            )
            tx.sign_input(0, payer.privkey, prevout.script_pubkey, payer.pubkey_bytes)
            return tx.serialize().hex()

        tx1_hex = build_spend(recipient1)
        tx2_hex = build_spend(recipient2)
        r1 = group1[0].submit_tx(tx1_hex)
        r2 = group2[0].submit_tx(tx2_hex)
        _p(f"    side 1 accepted tx {r1['txid'][:16]}: {r1['accepted']}")
        _p(f"    side 2 accepted tx {r2['txid'][:16]}: {r2['accepted']}")
        assert r1["accepted"] and r2["accepted"]
        assert r1["txid"] != r2["txid"]

        _p("\n[5] each side mines independently on its own fork...")
        # Mined sequentially rather than racing both groups at once: two
        # groups mining concurrently can easily end up with *exactly*
        # equal cumulative work (identical bits, similar block counts),
        # and a real tie is never resolved by cumulative-work fork choice
        # alone (neither side's `work > tip.work` ever fires) — genuine
        # Nakamoto-consensus behavior, not a bug, but not a stalemate this
        # demo should leave to chance. Mining side 1 to completion first,
        # then side 2 strictly further with side 1 stopped, guarantees a
        # real, unambiguous winner every run.
        for n in group1:
            n.mine_start()
        t0 = time.time()
        while time.time() - t0 < max_wait:
            if min(n.status()["height"] for n in group1) >= shared_height + target_height_each_side:
                break
            time.sleep(0.3)
        for n in group1:
            n.mine_stop()

        for n in group2:
            n.mine_start()
        t0 = time.time()
        while time.time() - t0 < max_wait:
            if min(n.status()["height"] for n in group2) >= shared_height + target_height_each_side + 2:
                break
            time.sleep(0.3)
        for n in group2:
            n.mine_stop()
        time.sleep(0.5)

        tip1, tip2 = group1[0].status()["tip"], group2[0].status()["tip"]
        h1f, h2f = group1[0].status()["height"], group2[0].status()["height"]
        _p(f"    side 1 (alpha/beta):  height={h1f} tip={tip1[:16]}")
        _p(f"    side 2 (gamma/delta): height={h2f} tip={tip2[:16]}")
        assert tip1 != tip2, "the two sides should have mined genuinely different chains"
        bal1_r1 = group1[0].balance(recipient1.address)
        bal2_r2 = group2[0].balance(recipient2.address)
        _p(f"    recipient 1 balance on side 1: {bal1_r1:,} sats (its own spend confirmed)")
        _p(f"    recipient 2 balance on side 2: {bal2_r2:,} sats (its own spend confirmed)")
        assert bal1_r1 > 0 and bal2_r2 > 0

        _p("\n[6] HEALING the partition...")
        for a in group1:
            for b in group2:
                a.heal(b)
                b.heal(a)
        time.sleep(1.0)

        _p("    waiting for every node to reorg onto one winning chain...")
        t0 = time.time()
        last_resync = t0
        while time.time() - t0 < max_wait:
            tips = {n.status()["tip"] for n in nodes}
            if len(tips) == 1:
                break
            # A single heal-time sync request can be lost to an in-flight
            # handshake race or a dropped message; keep nudging every few
            # seconds rather than relying on exactly one round trip.
            if time.time() - last_resync > 3.0:
                for a in group1:
                    for b in group2:
                        a.p2p_resync(b)
                        b.p2p_resync(a)
                last_resync = time.time()
            time.sleep(0.5)
        else:
            _p("    !! never converged — dumping diagnostics !!")
            for n in nodes:
                st = n.status()
                _p(f"    {n.name}: height={st['height']} tip={st['tip'][:16]} peers={st['peers']}")
                _p(f"      log tail: {_get(n.rpc_base, '/log?n=15')['log']}")
            raise RuntimeError("network never re-converged after healing")

        final_tip = nodes[0].status()["tip"]
        final_heights = {n.name: n.status()["height"] for n in nodes}
        _p(f"    ALL 4 NODES CONVERGED on tip {final_tip[:16]}")
        _p(f"    heights: {final_heights}")

        winner = "side 1 (recipient1)" if final_tip == tip1 else "side 2 (recipient2)"
        _p(f"    the surviving chain is {winner}'s fork")

        _p("\n[7] verifying the loser's spend is gone EVERYWHERE, winner's is confirmed EVERYWHERE:")
        for n in nodes:
            b1 = n.balance(recipient1.address)
            b2 = n.balance(recipient2.address)
            _p(f"    {n.name}: recipient1={b1:,}  recipient2={b2:,}")
        winning_recipient = recipient1 if final_tip == tip1 else recipient2
        losing_recipient = recipient2 if final_tip == tip1 else recipient1
        for n in nodes:
            assert n.balance(winning_recipient.address) > 0, f"{n.name} should confirm the winning spend"
            assert n.balance(losing_recipient.address) == 0, f"{n.name} must not confirm the losing double-spend"

        _p("\n" + "=" * 72)
        _p("PARTITION DEMO PASSED: real reorg, real double-spend correctly resolved,")
        _p("all 4 independent node processes converge on one identical ledger.")
        _p("=" * 72)

    finally:
        for n in nodes:
            n.stop()
